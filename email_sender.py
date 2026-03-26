"""
Sends the daily acquisition digest email.
Uses Gmail SMTP with an App Password (safer than storing your main password).
"""
import smtplib
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text      import MIMEText
from datetime             import datetime

from config import (
    EMAIL_SENDER, EMAIL_PASSWORD, EMAIL_RECIPIENTS,
    SMTP_HOST, SMTP_PORT,
)

logger = logging.getLogger(__name__)


# ── HTML template ─────────────────────────────────────────────────────────────

def _listing_html(listing: dict, index: int) -> str:
    color = "#1a56db" if index % 2 == 0 else "#1e429f"
    return f"""
    <div style="border:1px solid #e5e7eb; border-radius:8px; padding:16px;
                margin-bottom:16px; background:#ffffff;">
      <div style="display:flex; justify-content:space-between; align-items:flex-start;">
        <div>
          <span style="background:{color}; color:#fff; font-size:11px;
                       padding:2px 8px; border-radius:4px; font-weight:600;">
            {listing['source']}
          </span>
          <h3 style="margin:8px 0 4px; font-size:16px; color:#111827;">
            <a href="{listing['url']}" style="color:#1a56db; text-decoration:none;">
              {listing['title']}
            </a>
          </h3>
          <p style="margin:0; font-size:13px; color:#6b7280;">
            📍 {listing.get('location','N/C')} &nbsp;|&nbsp;
            💶 {listing.get('price','N/C')} &nbsp;|&nbsp;
            🗓 {listing.get('date','N/C')}
          </p>
        </div>
      </div>
      {"<p style='margin:10px 0 0; font-size:13px; color:#374151;'>" + listing['description'] + "</p>" if listing.get('description') else ""}
      <a href="{listing['url']}" style="display:inline-block; margin-top:10px;
         font-size:13px; color:#1a56db; text-decoration:underline;">
        Voir l'annonce →
      </a>
    </div>"""


def _build_html(new_listings: list[dict]) -> str:
    today  = datetime.now().strftime("%d %B %Y")
    count  = len(new_listings)
    cards  = "\n".join(_listing_html(l, i) for i, l in enumerate(new_listings))

    s = "s" if count > 1 else ""
    summary = (
        f"🎯 {count} nouvelle{s} annonce{s} détectée{s} aujourd'hui"
        if count > 0
        else "✅ Aucune nouvelle annonce aujourd'hui."
    )
    no_listings_msg = "<p style='color:#6b7280; text-align:center; padding:32px 0;'>L'agent repassera demain.</p>"
    body = cards if count > 0 else no_listings_msg

    return f"""
<!DOCTYPE html>
<html lang="fr">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0; padding:0; background:#f3f4f6; font-family: -apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0">
    <tr><td align="center" style="padding:32px 16px;">
      <table width="640" style="max-width:640px; width:100%;">

        <!-- Header -->
        <tr><td style="background:#1e3a5f; border-radius:12px 12px 0 0; padding:28px 32px;">
          <h1 style="margin:0; color:#ffffff; font-size:22px;">
            🚛 Acquisitions · Commissionnaire de Transport
          </h1>
          <p style="margin:6px 0 0; color:#93c5fd; font-size:14px;">
            Digest du {today}
          </p>
        </td></tr>

        <!-- Summary bar -->
        <tr><td style="background:#dbeafe; padding:14px 32px;">
          <p style="margin:0; font-size:15px; color:#1e3a8a; font-weight:600;">
            {summary}
          </p>
        </td></tr>

        <!-- Listings -->
        <tr><td style="background:#f9fafb; padding:24px 32px;">
          {body}
        </td></tr>

        <!-- Footer -->
        <tr><td style="background:#1e3a5f; border-radius:0 0 12px 12px; padding:18px 32px;">
          <p style="margin:0; font-size:12px; color:#93c5fd;">
            Sources scannées : Fusacq · Cession PME · Transentreprise · Alvo · BPI France · Remicom · Transmibat &nbsp;|&nbsp;
            Zones : France 🇫🇷 · Suisse 🇨🇭
          </p>
        </td></tr>

      </table>
    </td></tr>
  </table>
</body>
</html>"""


def _build_plain(new_listings: list[dict]) -> str:
    today = datetime.now().strftime("%d/%m/%Y")
    if not new_listings:
        return f"Digest du {today}\n\nAucune nouvelle annonce aujourd'hui.\n"
    lines = [f"Digest Acquisitions – Commissionnaire de Transport – {today}", ""]
    for l in new_listings:
        lines.append(f"[{l['source']}] {l['title']}")
        lines.append(f"  📍 {l.get('location','N/C')}  |  💶 {l.get('price','N/C')}  |  🗓 {l.get('date','N/C')}")
        lines.append(f"  {l['url']}")
        if l.get("description"):
            lines.append(f"  {l['description'][:200]}")
        lines.append("")
    return "\n".join(lines)


# ── Public API ────────────────────────────────────────────────────────────────

def send_digest(new_listings: list[dict], force: bool = False):
    """
    Send the daily email digest.

    Parameters
    ----------
    new_listings : list[dict]   New listings found today.
    force        : bool         Send even when there are 0 new listings.
    """
    if not new_listings and not force:
        logger.info("No new listings — skipping email.")
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = (
        f"🚛 {len(new_listings)} nouvelle(s) cible(s) acquisition"
        if new_listings
        else "🚛 Digest acquisition – rien de nouveau aujourd'hui"
    )
    msg["From"]    = EMAIL_SENDER
    msg["To"]      = ", ".join(EMAIL_RECIPIENTS)

    msg.attach(MIMEText(_build_plain(new_listings), "plain", "utf-8"))
    msg.attach(MIMEText(_build_html(new_listings),  "html",  "utf-8"))

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.ehlo()
            server.starttls()
            server.login(EMAIL_SENDER, EMAIL_PASSWORD)
            server.sendmail(EMAIL_SENDER, EMAIL_RECIPIENTS, msg.as_string())
        logger.info("Digest sent to %s", EMAIL_RECIPIENTS)
    except smtplib.SMTPException as exc:
        logger.error("Failed to send email: %s", exc)
        raise
