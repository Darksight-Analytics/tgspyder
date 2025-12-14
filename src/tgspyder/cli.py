#!/usr/bin/env python3

import re
import os
import csv
import sys
import json
import asyncio
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from telethon.sync import TelegramClient
from telethon import functions, types, errors
from argparse import RawDescriptionHelpFormatter
from colorama import init, Fore, Style

# ---------------------------
# Rich (progress bars)
# ---------------------------

def ensure_rich():
    try:
        from rich.console import Console  # noqa
        from rich.progress import Progress  # noqa
        from rich.panel import Panel  # noqa
        from rich.text import Text  # noqa
        from rich import box  # noqa
    except ImportError:
        print(
            "\n❌ Progress bars require the 'rich' library.\n"
            "Install it with:\n"
            "  python -m pip install rich\n"
        )
        sys.exit(1)

ensure_rich()

from rich.console import Console
from rich.progress import (
    Progress,
    SpinnerColumn,
    BarColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
    MofNCompleteColumn,
    TaskProgressColumn,
)

console = Console()

# Configuration file path (to store API credentials)
CONFIG_PATH = os.path.expanduser("~/.tgspyder.conf")
# Default Telethon session name
SESSION_NAME = "tgspyder"

BANNER = r"""
___________________________________________________________________________

    |  ████████╗ ██████╗ ███████╗██████╗ ██╗   ██╗██████╗ ███████╗██████╗  
    |  ╚══██╔══╝██╔════╝ ██╔════╝██╔══██╗╚██╗ ██╔╝██╔══██╗██╔════╝██╔══██╗
    |     ██║   ██║  ███╗███████╗██████╔╝ ╚████╔╝ ██║  ██║█████╗  ██████╔╝
    |     ██║   ██║   ██║╚════██║██╔═══╝   ╚██╔╝  ██║  ██║██╔══╝  ██╔══██╗
    |     ██║   ╚██████╔╝███████║██║        ██║   ██████╔╝███████╗██║  ██║
    |     ╚═╝    ╚═════╝ ╚══════╝╚═╝        ╚═╝   ╚═════╝ ╚══════╝╚═╝  ╚═╝
    |_____________________________________________________________________
    |                                                                     |
    | [Telegram OSINT CLI Tool by Darksight Analytics]                    |
    | [>>] Telegram Framework v1.0                                        |
    | [>>] @Authors, Valdemar Balle                                       |
    |_____________________________________________________________________|

"""


def show_banner():
    # Plain white banner, no Rich panel/box, no colors
    console.print(BANNER, style="white")


def ensure_event_loop():
    """
    Ensure there is an asyncio event loop for Telethon to use.
    Required on Python 3.12+, where get_event_loop() no longer creates one.
    """
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)


def ensure_pysocks():
    """
    Telethon needs PySocks (module name: 'socks') when using SOCKS proxies.
    Prevents 'No module named socks' crashes and gives a clear message.
    """
    try:
        import socks  # noqa: F401
    except ImportError:
        console.print(
            "\n[bold red]❌ Proxy support requires PySocks, which is not installed.[/bold red]\n"
            "Install dependencies with:\n"
            "  pip install -r requirements.txt\n\n"
            "Or manually:\n"
            "  python -m pip install pysocks\n"
        )
        sys.exit(1)


# ---------------------------
# Output folders
# ---------------------------

def _stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _safe_name(s: str) -> str:
    s = re.sub(r"\W+", "_", (s or "").strip())
    s = s.strip("_")
    return s[:80] if s else "target"


def _out_dir(subdir: str | None = None) -> Path:
    """
    Creates output folders relative to where the user runs the command.

    TGSpyder Output/
      members/
      chats/
      crawled_links/
    """
    base = Path.cwd() / "TGSpyder Output"
    if subdir:
        base = base / subdir
    base.mkdir(parents=True, exist_ok=True)
    return base


# ---------------------------
# Config
# ---------------------------

def load_config():
    """Load API credentials, login mode, and proxy from config file, if it exists."""
    if os.path.isfile(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            return (
                data.get("api_id"),
                data.get("api_hash"),
                data.get("phone"),
                data.get("bot_token"),
                data.get("proxy"),
            )
        except Exception as e:
            console.print(f"[yellow]Warning:[/yellow] Unable to read config '{CONFIG_PATH}'. Details: {e}")
    return None, None, None, None, None


def save_config(api_id, api_hash, phone=None, bot_token=None, proxy=None):
    """Save API credentials, login info, and proxy to config file."""
    data = {
        "api_id": api_id,
        "api_hash": api_hash,
        "phone": phone if phone else "",
        "bot_token": bot_token if bot_token else "",
        "proxy": proxy if proxy else "",
    }
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except Exception as e:
        console.print(f"[yellow]Warning:[/yellow] Unable to write config '{CONFIG_PATH}'. Details: {e}")


def update_proxy_in_config(new_proxy_str: str | None):
    """Update only the proxy value in the existing config (keeps creds)."""
    api_id, api_hash, phone, bot_token, _ = load_config()
    if api_id is None or api_hash is None:
        console.print("[red]No config found yet.[/red] Run tgspyder once to register API ID + API Hash.")
        return False
    save_config(api_id, api_hash, phone=phone, bot_token=bot_token, proxy=new_proxy_str or "")
    return True


def parse_proxy(proxy_str):
    """Parse the proxy configuration string into Telethon proxy format."""
    if not proxy_str:
        return None
    proxy_str = proxy_str.strip()

    if "://" in proxy_str:
        parsed = urlparse(proxy_str)
        proxy_type = parsed.scheme
        host = parsed.hostname
        port = parsed.port
        username = parsed.username
        password = parsed.password
    else:
        parts = proxy_str.split(":")
        if len(parts) < 3:
            raise ValueError(
                "Invalid proxy string. Expected 'type:host:port' or 'scheme://user:pass@host:port'."
            )
        proxy_type = parts[0]
        host = parts[1]
        port = int(parts[2]) if parts[2].isdigit() else None
        username = None
        password = None
        if len(parts) == 4:
            username = parts[3]
        elif len(parts) >= 5:
            username = parts[3]
            password = ":".join(parts[4:])

    if not host or not port or not proxy_type:
        raise ValueError("Proxy host, port, or type is missing.")

    proxy = {"proxy_type": proxy_type, "addr": host, "port": port}
    if username:
        proxy["username"] = username
    if password:
        proxy["password"] = password
    return proxy


# ---------------------------
# Sticker pack creator
# ---------------------------

def extract_sticker_short_name(value: str) -> str:
    raw = value.strip()
    if raw.startswith("http://") or raw.startswith("https://") or "t.me/" in raw:
        if not raw.startswith("http"):
            raw = "https://" + raw.lstrip("/")
        parsed = urlparse(raw)
        path = parsed.path.strip("/")
        parts = path.split("/")
        if len(parts) >= 2:
            return parts[1]
        elif len(parts) == 1:
            return parts[0]
        raise ValueError(f"Unable to parse sticker pack short name from URL: {value}")
    return raw.split()[0]


def sticker_pack_creator(client, pack_input):
    try:
        short_name = extract_sticker_short_name(pack_input)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        return

    console.print(f"[cyan]Resolved sticker pack input[/cyan] '{pack_input}' -> [bold]{short_name}[/bold]")
    try:
        result = client(
            functions.messages.GetStickerSetRequest(
                stickerset=types.InputStickerSetShortName(short_name),
                hash=0
            )
        )
    except errors.RPCError as e:
        console.print(f"[red]Unable to retrieve sticker pack[/red] '{short_name}'. Telegram API response: {e}")
        return
    except Exception as e:
        console.print(f"[red]Unexpected error requesting sticker pack[/red] '{short_name}': {e}")
        return

    sticker_set = result.set if hasattr(result, "set") else result
    sticker_set_id = getattr(sticker_set, "id", None)
    if sticker_set_id is None:
        console.print("[red]Sticker set retrieved but ID missing.[/red]")
        return

    creator_id = sticker_set_id >> 32
    console.print(f"[green]Sticker Pack creator ID (inferred):[/green] {creator_id}")

    try:
        creator_entity = client.get_entity(creator_id)
        if getattr(creator_entity, "username", None):
            console.print(f"Creator username: [bold]@{creator_entity.username}[/bold]")
        if getattr(creator_entity, "first_name", None):
            name = creator_entity.first_name
            if getattr(creator_entity, "last_name", None):
                name += " " + creator_entity.last_name
            console.print(f"Creator name: [bold]{name}[/bold]")
    except ValueError:
        console.print("[yellow]Creator profile could not be resolved (Telegram limitation).[/yellow]")
    except Exception as e:
        console.print(f"[red]Creator profile access error:[/red] {e}")


# ---------------------------
# Scrapers (with progress bars)
# ---------------------------

def _progress():
    return Progress(
        SpinnerColumn(style="cyan"),
        TextColumn("[bold]{task.description}[/bold]"),
        BarColumn(),
        TaskProgressColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        TimeRemainingColumn(),
        console=console,
        transient=False,
    )


def scrape_members(client, entity, output_name):
    output_name = _safe_name(output_name)
    out_dir = _out_dir("members")

    with console.status(f"[cyan]Downloading members list for[/cyan] [bold]{output_name}[/bold]..."):
        try:
            participants = client.get_participants(entity, aggressive=True)
        except errors.RPCError as e:
            console.print(f"[red]Unable to retrieve member list[/red] for '{output_name}'. Telegram API response: {e}")
            return
        except Exception as e:
            console.print(f"[red]Unexpected error retrieving members[/red] for '{output_name}': {e}")
            return

    filename = out_dir / f"members_{output_name}_{_stamp()}.csv"

    total = len(participants)
    with _progress() as progress:
        task = progress.add_task(f"Writing members CSV ({output_name})", total=total)

        with open(filename, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["user_id", "username", "name", "profile_link", "phone"])

            for user in participants:
                uid = user.id
                username = user.username or ""
                first_name = user.first_name or ""
                last_name = user.last_name or ""
                name = (first_name + " " + last_name).strip() or ""
                profile_link = f"https://t.me/{username}" if username else ""
                phone = user.phone or ""
                writer.writerow([uid, username, name, profile_link, phone])
                progress.advance(task, 1)

    console.print(f"[green]Saved members list to[/green] '{filename}'.")


def scrape_messages_and_invites(client, entity, output_name, save_chats=False, save_invites=False):
    output_name = _safe_name(output_name)

    msg_writer = None
    invites_writer = None
    msg_f = None
    inv_f = None
    invite_links_set = set()

    msg_file = None
    inv_file = None

    if save_chats:
        chats_dir = _out_dir("chats")
        msg_file = chats_dir / f"messages_{output_name}_{_stamp()}.csv"
        msg_f = open(msg_file, "w", newline="", encoding="utf-8")
        msg_writer = csv.writer(msg_f)
        msg_writer.writerow(["message_id", "date", "sender", "text"])

    if save_invites:
        invites_dir = _out_dir("crawled_links")
        inv_file = invites_dir / f"crawled_links_{output_name}_{_stamp()}.csv"
        inv_f = open(inv_file, "w", newline="", encoding="utf-8")
        invites_writer = csv.writer(inv_f)
        invites_writer.writerow(["invite_link"])

    messages_seen = 0
    invites_found = 0

    try:
        with _progress() as progress:
            task = progress.add_task(f"Crawling messages ({output_name})", total=None)

            for message in client.iter_messages(entity, reverse=True):
                messages_seen += 1
                progress.update(
                    task,
                    description=f"Crawling ({output_name}) • msgs={messages_seen} • invites={invites_found}",
                )
                progress.advance(task, 1)

                text = message.message or ""
                if not text and message.media:
                    if isinstance(message.media, types.MessageMediaPhoto):
                        text = "[Photo]"
                    elif isinstance(message.media, types.MessageMediaDocument):
                        doc = message.media.document
                        if any(isinstance(attr, types.DocumentAttributeSticker) for attr in getattr(doc, "attributes", [])):
                            text = "[Sticker]"
                        else:
                            text = "[Document]"
                    else:
                        text = "[Media]"

                sender_name = ""
                try:
                    sender = message.sender
                except Exception:
                    sender = None

                if sender:
                    fname = getattr(sender, "first_name", "") or ""
                    lname = getattr(sender, "last_name", "") or ""
                    full_name = (fname + " " + lname).strip()
                    sender_name = full_name or (getattr(sender, "username", "") or str(sender.id))
                else:
                    sender_name = getattr(entity, "title", "") or "Channel"

                if save_chats and msg_writer:
                    msg_writer.writerow([
                        message.id,
                        message.date.strftime("%Y-%m-%d %H:%M:%S"),
                        sender_name,
                        text
                    ])

                if save_invites and invites_writer and text:
                    links = re.findall(r'(?:https?://)?t\.me/(?:joinchat/|\+)?[A-Za-z0-9_-]+', text)
                    for link in links:
                        if not link.startswith("http"):
                            link = "https://" + link
                        link = link.strip().rstrip(".,)")
                        if link not in invite_links_set:
                            invite_links_set.add(link)
                            invites_writer.writerow([link])
                            invites_found += 1

    except errors.RPCError as e:
        console.print(f"[red]Unable to iterate messages[/red] for '{output_name}'. Telegram API response: {e}")
    except Exception as e:
        console.print(f"[red]Unexpected error while crawling[/red] '{output_name}': {e}")
    finally:
        if msg_f:
            msg_f.close()
            if save_chats and msg_file:
                console.print(f"[green]Saved chat messages to[/green] '{msg_file}'.")
        if inv_f:
            inv_f.close()
            if save_invites and inv_file:
                console.print(f"[green]Saved crawled invite links to[/green] '{inv_file}'.")


# ---------------------------
# User lookup
# ---------------------------

def lookup_user(client, identifier: str):
    raw = identifier.strip()
    username = raw[1:] if raw.startswith("@") else (None if raw.isdigit() else raw)
    user_id = int(raw) if raw.isdigit() else None

    try:
        entity = client.get_entity(username) if username else client.get_entity(user_id)
    except Exception as e:
        console.print(f"[red]Unable to resolve user[/red] '{identifier}': {e}")
        return

    if not isinstance(entity, types.User):
        console.print(f"[yellow]'{identifier}' resolved but is not a user.[/yellow]")
        return

    console.print("[bold]User Lookup Result[/bold]")
    console.print(f"ID:        [bold]{entity.id}[/bold]")
    console.print(f"Username:  [bold]@{entity.username}[/bold]" if entity.username else "Username:  [dim][none][/dim]")
    full_name = ((entity.first_name or "") + " " + (entity.last_name or "")).strip()
    console.print(f"Name:      [bold]{full_name}[/bold]" if full_name else "Name:      [dim][none][/dim]")
    console.print(f"Phone:     {entity.phone if entity.phone else '[hidden/none]'}")
    if entity.username:
        console.print(f"Profile:   https://t.me/{entity.username}")
    console.print("")


# ---------------------------
# Main CLI
# ---------------------------

def main():
    import argparse

    show_banner()
    ensure_event_loop()
    init(autoreset=True)

    # NOTE: cyber_help_banner removed entirely to avoid NameError bugs.
    description = (
        "Perform Telegram OSINT from your terminal.\n\n"
        "Usage Examples:\n"
        "  tgspyder --sticker-pack <url_or_shortname>\n"
        "  tgspyder <group_url> --members --chats\n"
        "  tgspyder --set-proxy socks5://127.0.0.1:9050\n"
        "  tgspyder --remove-proxy\n"
    )

    parser = argparse.ArgumentParser(
        prog="tgspyder",
        description=description,
        formatter_class=lambda prog: RawDescriptionHelpFormatter(prog, max_help_position=40)
    )

    parser.add_argument("target", nargs="?", help="🎯 Target Telegram group/channel (username or invite link)")
    parser.add_argument("--members", action="store_true", help="📋 Scrape and save member list")
    parser.add_argument("--chats", action="store_true", help="💬 Scrape chat messages")
    parser.add_argument("--crawl-invites", action="store_true", dest="crawl_invites",
                        help="🔗 Extract t.me invite links from chat history")
    parser.add_argument("--sticker-pack", "-s", dest="sticker_pack",
                        help="🎭 Identify creator of sticker pack (shortname or full URL)")
    parser.add_argument("--user", dest="user_lookup", help="🧍 Lookup Telegram user by ID or username")

    parser.add_argument("--proxy", help="🌐 One-off proxy override for this run (not saved)")
    parser.add_argument("--set-proxy", dest="set_proxy",
                        help="🌐 Save proxy to config for future runs (e.g. socks5://127.0.0.1:9050)")
    parser.add_argument("--remove-proxy", action="store_true",
                        help="🧹 Remove the saved proxy from config")

    parser.add_argument("--reset-creds", action="store_true", help="🔐 Reset API credentials and re-authenticate")

    args = parser.parse_args()

    api_id, api_hash, phone, bot_token, saved_proxy_str = load_config()

    if args.remove_proxy:
        ok = update_proxy_in_config(None)
        if ok:
            console.print("[green]✅ Saved proxy removed from config.[/green]")
        if not (args.target or args.sticker_pack or args.user_lookup or args.reset_creds or args.set_proxy):
            sys.exit(0)
        api_id, api_hash, phone, bot_token, saved_proxy_str = load_config()

    if args.set_proxy:
        ensure_pysocks()
        _ = parse_proxy(args.set_proxy)
        ok = update_proxy_in_config(args.set_proxy.strip())
        if ok:
            console.print("[green]✅ Proxy saved to config.[/green]")
        api_id, api_hash, phone, bot_token, saved_proxy_str = load_config()

    if args.reset_creds or api_id is None or api_hash is None:
        console.print("[yellow]No valid configuration found. Please enter your Telegram API credentials:[/yellow]")
        api_id = int(input("API ID: ").strip())
        api_hash = input("API Hash: ").strip()

        mode = input("Are you using a (u)ser account or a (b)ot token? [u/b]: ").strip().lower()
        phone = None
        bot_token = None
        if mode.startswith("b"):
            bot_token = input("Enter bot token: ").strip()
        else:
            phone = input("Enter phone number (international format, e.g. +123456789): ").strip()

        save_config(api_id, api_hash, phone, bot_token, proxy=saved_proxy_str or "")
        try:
            os.remove(f"{SESSION_NAME}.session")
        except FileNotFoundError:
            pass

    effective_proxy_str = None
    if args.proxy:
        effective_proxy_str = args.proxy.strip()
    elif saved_proxy_str and saved_proxy_str.strip():
        effective_proxy_str = saved_proxy_str.strip()

    proxy = None
    if effective_proxy_str:
        ensure_pysocks()
        proxy = parse_proxy(effective_proxy_str)
        console.print(f"🌐 Using proxy: [bold]{effective_proxy_str}[/bold]")

    client = TelegramClient(SESSION_NAME, api_id, api_hash, proxy=proxy)

    try:
        with console.status("[cyan]Connecting to Telegram...[/cyan]"):
            client.connect()
    except Exception as e:
        console.print(
            "[red]Unable to establish a connection to Telegram.[/red]\n"
            "Please verify your network connectivity and, if applicable, your proxy configuration.\n"
            f"Details: {e}"
        )
        sys.exit(1)

    if not client.is_user_authorized():
        if bot_token:
            with console.status("[cyan]Authorizing bot...[/cyan]"):
                client.start(bot_token=bot_token)
        else:
            client.send_code_request(phone)
            code = input("Enter the login code you received: ").strip()
            try:
                with console.status("[cyan]Signing in...[/cyan]"):
                    client.sign_in(phone=phone, code=code)
            except errors.SessionPasswordNeededError:
                pw = input("Two-step verification password: ").strip()
                with console.status("[cyan]Completing 2FA sign-in...[/cyan]"):
                    client.sign_in(password=pw)

    if args.user_lookup:
        lookup_user(client, args.user_lookup)
        if not args.target and not args.sticker_pack:
            client.disconnect()
            sys.exit(0)

    if args.sticker_pack:
        sticker_pack_creator(client, args.sticker_pack)
        if not args.target:
            client.disconnect()
            sys.exit(0)

    if args.target:
        target = args.target
        try:
            with console.status(f"[cyan]Resolving target[/cyan] [bold]{target}[/bold]..."):
                if "joinchat" in target or target.startswith("https://t.me/+") or target.startswith("t.me/+"):
                    invite_code = target.split("/")[-1]
                    if invite_code.startswith("+"):
                        invite_code = invite_code[1:]
                    try:
                        updates = client(functions.messages.ImportChatInviteRequest(invite_code))
                        if updates.chats:
                            entity = updates.chats[0]
                        else:
                            entity = client.get_entity(target)
                    except errors.UserAlreadyParticipantError:
                        entity = client.get_entity(target)
                else:
                    entity = client.get_entity(target)
        except Exception as e:
            console.print(f"[red]Unable to resolve target[/red] '{target}': {e}")
            client.disconnect()
            sys.exit(1)

        if hasattr(entity, "title") and entity.title:
            out_name = entity.title
        elif getattr(entity, "username", None):
            out_name = entity.username
        else:
            out_name = str(getattr(entity, "id", "target"))

        if args.members:
            scrape_members(client, entity, out_name)
        if args.chats or args.crawl_invites:
            scrape_messages_and_invites(
                client, entity, out_name,
                save_chats=args.chats,
                save_invites=args.crawl_invites
            )

    client.disconnect()
    console.print("[green]✅ Done.[/green]")


if __name__ == "__main__":
    main()
