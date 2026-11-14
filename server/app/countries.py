"""Country packs: Mindy is global, so local facts live here as data, not code.
Picked from the phone number's country code (or the user's own choice). Add a country = add a dict.
Keep this list factual and conservative: official portals and helplines only; Mindy says "check the official site"."""

PACKS = {
    "IN": {"name": "India", "cc": "91", "cur": "₹", "emergency": "112", "pay": "upi",
           "scam": "Call 1930 or report at cybercrime.gov.in. Report fraud calls and SMS on Chakshu at sancharsaathi.gov.in.",
           "benefits": "https://www.myscheme.gov.in", "docs": ["insurance", "puc", "driving licence", "rc", "passport"],
           "scams": ["KYC update links", "electricity cut-off messages", "part-time job / task scams", "fake courier or customs calls", "digital arrest calls"]},
    "GB": {"name": "United Kingdom", "cc": "44", "cur": "£", "emergency": "999", "pay": "link",
           "scam": "Forward scam texts to 7726 (free). Report fraud to the police fraud service at actionfraud.police.uk, and call your bank on the number on your card.",
           "benefits": "https://www.gov.uk/benefits-calculators", "docs": ["mot", "car tax", "insurance", "tv licence", "passport", "railcard"],
           "scams": ["Royal Mail / Evri missed-parcel texts", "HMRC tax refund messages", "'Hi Mum' new-number texts", "fake bank safe-account calls"]},
    "US": {"name": "United States", "cc": "1", "cur": "$", "emergency": "911", "pay": "link",
           "scam": "Forward scam texts to 7726 (SPAM). Report at reportfraud.ftc.gov.",
           "benefits": "https://www.usa.gov/benefit-finder", "docs": ["registration", "inspection", "insurance", "driver's license", "passport"],
           "scams": ["toll-road unpaid-fee texts", "fake USPS delivery texts", "IRS / SSA impersonation calls", "gift-card payment requests"]},
    "AE": {"name": "UAE", "cc": "971", "cur": "AED ", "emergency": "999", "pay": "link",
           "scam": "Report to the police eCrime portal (ecrime.ae) or call 999. Never share an OTP or UAE Pass code.",
           "benefits": "https://u.ae", "docs": ["mulkiya", "insurance", "emirates id", "passport"],
           "scams": ["fake traffic-fine links", "Emirates ID update calls", "job offer fees"]},
    "NG": {"name": "Nigeria", "cc": "234", "cur": "₦", "emergency": "112", "pay": "link",
           "scam": "Call your bank first, then report to the police on 112. Never share your BVN or OTP.",
           "benefits": "", "docs": ["vehicle licence", "insurance", "nin", "passport"],
           "scams": ["BVN update messages", "fake POS alerts", "investment doubling schemes"]},
    "KE": {"name": "Kenya", "cc": "254", "cur": "KSh ", "emergency": "999", "pay": "mpesa",
           "scam": "Forward Safaricom scam SMS to 333 for free. Never share your M-Pesa PIN.",
           "benefits": "https://www.ecitizen.go.ke", "docs": ["insurance", "inspection", "driving licence", "passport"],
           "scams": ["'sent to you by mistake' M-Pesa messages", "fake loan offers", "SIM swap calls"]},
    "BR": {"name": "Brasil", "cc": "55", "cur": "R$", "emergency": "190", "pay": "pix",
           "scam": "Ligue para o seu banco pelo número do cartão e registre um boletim de ocorrência. Nunca compartilhe códigos.",
           "benefits": "https://www.gov.br", "docs": ["ipva", "licenciamento", "cnh", "passaporte"],
           "scams": ["golpe do Pix", "falsa central do banco", "'oi mãe, troquei de número'"]},
    "MX": {"name": "México", "cc": "52", "cur": "MX$", "emergency": "911", "pay": "link",
           "scam": "Llama a tu banco y reporta a CONDUSEF. Nunca compartas tu NIP ni códigos.",
           "benefits": "https://www.gob.mx/bienestar", "docs": ["tenencia", "verificación", "licencia", "pasaporte"],
           "scams": ["llamadas de falso secuestro", "falso cobro de paquetería", "préstamos exprés"]},
    "ID": {"name": "Indonesia", "cc": "62", "cur": "Rp", "emergency": "112", "pay": "link",
           "scam": "Cek nomor rekening di cekrekening.id dan lapor ke bank Anda. Jangan bagikan kode OTP.",
           "benefits": "https://cekbansos.kemensos.go.id", "docs": ["stnk", "sim", "pajak kendaraan", "paspor"],
           "scams": ["file undangan .apk", "kurir paket palsu", "pinjol ilegal"]},
    "PH": {"name": "Philippines", "cc": "63", "cur": "₱", "emergency": "911", "pay": "link",
           "scam": "Report scams to the CICC hotline 1326 and to your bank or e-wallet. Never share your OTP or MPIN.",
           "benefits": "https://www.dswd.gov.ph", "docs": ["lto registration", "driver's license", "passport"],
           "scams": ["fake e-wallet promos", "parcel 'customs fee' texts", "task scams"]},
    "PK": {"name": "Pakistan", "cc": "92", "cur": "Rs ", "emergency": "15", "pay": "link",
           "scam": "Report cybercrime to the FIA helpline 1991 and call your bank. Never share your OTP or CNIC photos.",
           "benefits": "https://8171.bisp.gov.pk", "docs": ["vehicle token tax", "driving licence", "cnic", "passport"],
           "scams": ["fake BISP 8171 messages", "prize-winning calls", "bank verification calls"]},
    "BD": {"name": "Bangladesh", "cc": "880", "cur": "৳", "emergency": "999", "pay": "link",
           "scam": "Call 999 and your mobile-banking provider. Never share your PIN or OTP.",
           "benefits": "", "docs": ["vehicle fitness", "driving licence", "nid", "passport"],
           "scams": ["bKash/Nagad 'wrong send' calls", "fake job offers"]},
    "DE": {"name": "Deutschland", "cc": "49", "cur": "€", "emergency": "112", "pay": "link",
           "scam": "Rufen Sie Ihre Bank an und erstatten Sie Anzeige bei der Polizei (110 oder Online-Wache).",
           "benefits": "https://www.arbeitsagentur.de", "docs": ["tüv / hu", "versicherung", "führerschein", "reisepass"],
           "scams": ["'Hallo Mama' Nachrichten", "falsche Paket-SMS", "Schockanrufe"]},
    "FR": {"name": "France", "cc": "33", "cur": "€", "emergency": "112", "pay": "link",
           "scam": "Transférez les SMS frauduleux au 33700 et appelez votre banque.",
           "benefits": "https://www.mesdroitssociaux.gouv.fr", "docs": ["contrôle technique", "assurance", "permis", "passeport"],
           "scams": ["faux SMS de colis", "faux conseiller bancaire", "amendes ANTAI frauduleuses"]},
    "ES": {"name": "España", "cc": "34", "cur": "€", "emergency": "112", "pay": "link",
           "scam": "Llama al 017 (INCIBE, gratis y confidencial) y a tu banco.",
           "benefits": "https://www.seg-social.es", "docs": ["itv", "seguro", "carné de conducir", "pasaporte"],
           "scams": ["SMS falsos de Correos", "'hola mamá' por WhatsApp", "falso técnico del banco"]},
}
GLOBAL = {"name": "your country", "cc": "", "cur": "", "emergency": "112", "pay": "link",
          "scam": "Call your bank on the number printed on your card, and report to the police. Never share a PIN or one-time code.",
          "benefits": "", "docs": ["insurance", "driving licence", "passport", "id card"], "scams": ["fake delivery texts", "bank impersonation calls"]}
_BY_CC = sorted(((p["cc"], code) for code, p in PACKS.items()), key=lambda t: -len(t[0]))


def country_of(ext: str | None) -> str | None:
    digits = "".join(c for c in str(ext or "") if c.isdigit())
    if not digits or str(ext).startswith(("ig:", "tg:")):
        return None
    for cc, code in _BY_CC:
        if digits.startswith(cc):
            return code
    return None


def pack(code: str | None) -> dict:
    return PACKS.get((code or "").upper(), GLOBAL)


def for_user(db, user: dict) -> dict:
    code = user.get("country")
    if not code:
        exts = [a["ext"] for a in db.q("SELECT ext FROM accounts WHERE user_id=? ORDER BY rowid", (user["id"],))] if _has_accounts(db) else []
        code = next((c for c in (country_of(e) for e in exts + [user.get("wa_id")]) if c), None)
    p = dict(pack(code))
    p["code"] = code or ""
    return p


def _has_accounts(db) -> bool:
    try:
        db.one("SELECT 1 FROM accounts LIMIT 1")
        return True
    except Exception:
        return False


def money(p: dict, n: float) -> str:
    cur = p.get("cur") or ""
    return f"{cur}{n:,.0f}" if cur else f"{n:,.0f}"
