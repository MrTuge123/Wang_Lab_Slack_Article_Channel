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
from digest.notify.format import ZH_LABEL, impact_line

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


# Colors / fonts (inline styles only: email clients ignore <style> blocks and external CSS)
FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif"
INK, MUTED, FAINT, LINE, ACCENT, BG = "#1f2328", "#57606a", "#8c959f", "#e4e7eb", "#1a5fb4", "#f3f4f6"
SOURCE_NAMES = ["PubMed", "Europe PMC", "OpenAlex", "Semantic Scholar", "arXiv"]


def _authors(p, n=3):
    """'Wei Li, Meng Wang, Bo Chen … Yu Zhao' (first n, then the last author)."""
    a = p.get("authors") or []
    return ", ".join(a) if len(a) <= n + 1 else ", ".join(a[:n]) + " … " + a[-1]


def _date_range(sub):
    end = dt.date.today()
    start = end - dt.timedelta(days=sub["days_back"])
    fmt = lambda d: f"{d:%b} {d.day}"
    return f"{fmt(start)} – {fmt(end)}, {end.year}"


def _chip(text, fg, bg):
    return (f'<span style="display:inline-block;padding:2px 8px;margin:0 4px 4px 0;border-radius:10px;'
            f'background:{bg};color:{fg};font-size:12px;line-height:18px">{html.escape(text)}</span>')


def _paper_html(i, p):
    e = html.escape
    title_url = paper.url(p)
    journal = p["journal"].replace(" (preprint)", "")
    chips = _chip("Preprint", "#8a5300", "#fff4d6") if p.get("preprint") else ""
    chips += "".join(_chip(k, "#0b4a8b", "#e7f0fb") for k in p.get("keyword_hits", []))
    meta = f'<span style="font-style:italic">{e(journal)}</span>' if journal else ""
    if p.get("top_author"):
        a = p["top_author"]
        meta += (f' &nbsp;·&nbsp; {e(a["name"])} <span style="color:{FAINT}">'
                 f'(h-index {a["h"]}, {e(a["role"])})</span>')
    buttons = "".join(
        f'<a href="{e(u)}" style="display:inline-block;margin:0 6px 0 0;padding:6px 12px;border-radius:6px;'
        f'font-size:13px;text-decoration:none;'
        + (f'background:{ACCENT};color:#ffffff;' if j == 0 else f'border:1px solid {LINE};color:{ACCENT};')
        + f'">{e(label)}{" →" if j == 0 else ""}</a>'
        for j, (label, u) in enumerate(paper.links(p)))
    zh = (f'<p style="color:{INK};font-size:14px;line-height:22px;margin:0 0 12px">'
          f'<span style="color:{MUTED}">{e(ZH_LABEL)}</span>{e(p["summary_zh"])}</p>') if p.get("summary_zh") else ""
    return f"""
<tr><td style="padding:22px 28px;border-top:1px solid {LINE}">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>
    <td valign="top" width="34" style="padding-top:2px">
      <div style="width:24px;height:24px;border-radius:12px;background:{BG};color:{MUTED};font-size:12px;
                  font-weight:600;line-height:24px;text-align:center">{i}</div></td>
    <td valign="top">
      <a href="{e(title_url)}" style="color:{INK};font-size:16px;font-weight:600;line-height:22px;
         text-decoration:none">{e(p["title"])}</a>
      <div style="color:{MUTED};font-size:13px;line-height:19px;margin-top:4px">{meta}</div>
      <div style="color:{FAINT};font-size:12px;line-height:18px;margin-top:2px">{e(_authors(p))}</div>
      <div style="margin-top:8px">{chips}</div>
      <p style="color:{INK};font-size:14px;line-height:21px;margin:6px 0 12px">{e(p["summary"])}</p>{zh}
      <div>{buttons}</div>
    </td></tr></table>
</td></tr>"""


def build(top, sub, context=None):
    """One email: an HTML newsletter plus a plain-text version.
    context (optional): {"candidates": int, "found": {source name: count or error}}."""
    context = context or {}
    today = dt.date.today()
    n = len(top)
    subject = f"{n} new paper{'s' * (n != 1)} for {sub['name']} · {today:%b} {today.day}"
    searched = [s for s in SOURCE_NAMES if isinstance((context.get("found") or {}).get(s), int)] \
        or [s for s in SOURCE_NAMES if s in {x for p in top for x in p.get("sources", [])}]
    stats = f"{n} new paper{'s' * (n != 1)}"
    if context.get("candidates"):
        stats += f", picked from {context['candidates']} candidates"
    e = html.escape

    # --- plain text
    text = [f"{sub['name']} · weekly paper digest", f"{_date_range(sub)} · {stats}", ""]
    for i, p in enumerate(top, 1):
        text += [f"{i}. {p['title']}", f"   {impact_line(p)}", f"   {_authors(p)}",
                 "", "   " + p["summary"], ""]
        if p.get("summary_zh"):
            text += ["   " + ZH_LABEL + p["summary_zh"], ""]
        text += [f"   {label}: {u}" for label, u in paper.links(p)] + [""]
    text += ["Searched: " + ", ".join(searched)]

    # --- HTML
    preheader = e(top[0]["title"]) if top else ""
    body = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{e(subject)}</title></head>
<body style="margin:0;padding:0;background:{BG}">
<div style="display:none;max-height:0;overflow:hidden;opacity:0">{preheader}</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{BG}">
<tr><td align="center" style="padding:24px 12px">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
         style="max-width:640px;background:#ffffff;border-radius:10px;font-family:{FONT}">
    <tr><td style="padding:26px 28px 20px">
      <div style="color:{ACCENT};font-size:12px;font-weight:600;letter-spacing:1px;text-transform:uppercase">
        Weekly paper digest</div>
      <div style="color:{INK};font-size:24px;font-weight:700;line-height:30px;margin-top:6px">{e(sub["name"])}</div>
      <div style="color:{MUTED};font-size:14px;margin-top:4px">{e(_date_range(sub))} · {e(stats)}</div>
    </td></tr>
    {"".join(_paper_html(i, p) for i, p in enumerate(top, 1))}
    <tr><td style="padding:18px 28px 24px;border-top:1px solid {LINE};color:{FAINT};font-size:12px;line-height:18px">
      Searched {e(", ".join(searched))}. Ranked by author h-index, journal impact and keyword matches;
      summaries are written by an AI model and may contain mistakes.<br>
      Sent automatically by the {e(sub["name"])} paper digest. Reply to this email to stop receiving it.
    </td></tr>
  </table>
</td></tr></table></body></html>"""

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
