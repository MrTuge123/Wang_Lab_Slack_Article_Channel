"""Email over SMTP (e.g. a Gmail account with an app password).

Sender account (secrets, shared by all subscribers):
    SMTP_HOST      smtp.gmail.com
    SMTP_PORT      587 (STARTTLS, default) or 465 (SSL)
    SMTP_USER      literaturebot99@gmail.com
    SMTP_PASSWORD  the 16-character app password (spaces are ignored)
    SMTP_FROM      optional, defaults to SMTP_USER
Recipients, per subscriber under outputs.email:
    to: [a@umich.edu, b@umich.edu]      and/or
    to_env: EMAIL_TO_WANG_LAB           (a secret holding comma-separated addresses)
Recipients are Bcc'd, so they don't see each other's addresses.
"""
import datetime as dt
import html
import smtplib
import ssl
import time
from email.message import EmailMessage
from email.utils import formataddr

from digest import env, paper
from digest.notify.format import impact_line

NAME = "Email"
SENDER_NAME = "Paper Digest"


def destination(cfg):
    """(recipients, None) or (None, what's missing)."""
    to = cfg.get("to") or []
    to = [to] if isinstance(to, str) else list(to)
    if cfg.get("to_env"):
        to += [a.strip() for a in (env.get(cfg["to_env"]) or "").split(",") if a.strip()]
    missing = [n for n in ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD") if not env.get(n)]
    if not to:
        return None, "it has no recipients (outputs.email.to or to_env)"
    if missing:
        verb = "isn't" if len(missing) == 1 else "aren't"
        return None, f"{', '.join(missing)} {verb} set (.env locally, GitHub secrets in Actions)"
    return to, None


def build(top, sub):
    """One email: plain text plus an HTML version with clickable titles."""
    today = dt.date.today()
    subject = f"New papers for {sub['name']} · {today:%b} {today.day}"
    header = f"New papers for {sub['name']} (last {sub['days_back']} days)"

    text = [header, ""]
    items = []
    for p in top:
        text += [p["title"], paper.url(p), impact_line(p), p["summary"], ""]
        items.append(
            f'<p style="margin:20px 0 4px;font-size:15px"><a href="{html.escape(paper.url(p))}" '
            f'style="color:#1a0dab;font-weight:600;text-decoration:none">{html.escape(p["title"])}</a></p>'
            f'<div style="color:#666;font-size:13px">{html.escape(impact_line(p))}</div>'
            f'<p style="margin:6px 0 0;font-size:14px;line-height:1.5">{html.escape(p["summary"])}</p>')
    body = (f'<div style="font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;max-width:680px;color:#222">'
            f'<h2 style="font-size:18px;margin:0 0 4px">📰 {html.escape(header)}</h2>{"".join(items)}'
            f'<p style="color:#999;font-size:12px;margin-top:28px">Sent automatically by the lab paper digest.</p></div>')

    msg = EmailMessage()
    msg["Subject"] = subject
    msg.set_content("\n".join(text))
    msg.add_alternative(body, subtype="html")
    return [msg]


def preview(msg):
    """What --dry-run prints."""
    return f"Subject: {msg['Subject']}\n\n{msg.get_body(('plain',)).get_content()}"


def _connect(host, port, ctx):
    if port == 465:
        return smtplib.SMTP_SSL(host, port, context=ctx, timeout=60)
    server = smtplib.SMTP(host, port, timeout=60)
    server.starttls(context=ctx)
    return server


def send(recipients, msg):
    """Send via SMTP_PORT; if the server can't be reached, retry and also try Gmail's other
    port (587 STARTTLS <-> 465 SSL), since some networks (VPNs, campus Wi-Fi) block one of them."""
    host, port = env.get("SMTP_HOST"), int(env.get("SMTP_PORT") or 587)
    user, password = env.get("SMTP_USER"), (env.get("SMTP_PASSWORD") or "").replace(" ", "")
    sender = env.get("SMTP_FROM") or user
    for h in ("From", "To"):
        del msg[h]
    msg["From"] = formataddr((SENDER_NAME, sender))
    msg["To"] = formataddr((SENDER_NAME, sender))        # real recipients go as Bcc
    ctx = ssl.create_default_context()
    ports = [port] + [p for p in (587, 465) if p != port and port in (587, 465)]
    attempts = [(p, wait) for wait in (0, 15) for p in ports]     # every port, then again after 15 s
    for i, (p, wait) in enumerate(attempts):
        time.sleep(wait if p == ports[0] else 0)
        try:
            with _connect(host, p, ctx) as server:
                server.login(user, password)
                server.send_message(msg, from_addr=sender, to_addrs=recipients)
            return
        except smtplib.SMTPAuthenticationError:
            raise                                          # wrong password: retrying won't help
        except (smtplib.SMTPServerDisconnected, smtplib.SMTPConnectError, OSError) as e:
            if i == len(attempts) - 1:
                raise
            print(f"  Email: {host}:{p} failed ({e}); trying again...")
