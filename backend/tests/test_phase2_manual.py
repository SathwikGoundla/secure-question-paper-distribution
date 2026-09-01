"""
Phase 2 test script — exercises the real running server + real
PostgreSQL database. Not a committed pytest suite (see known
limitations); run manually for this phase's validation, mirroring the
Phase 1 testing approach.

Covers all 18 test cases required by the Phase 2 instructions.
"""

import time
import uuid

import httpx
import jwt as pyjwt
import psycopg2

from app.config import get_settings

_settings = get_settings()

BASE_URL = "http://127.0.0.1:8000/api/v1"
# Read from the same environment configuration the app itself uses —
# never hardcode credentials, even for a local test script (SEC-010).
DB_DSN = _settings.DATABASE_URL.replace("postgresql+psycopg2://", "postgresql://")
JWT_SECRET = _settings.JWT_SECRET_KEY

results = []


def check(name, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    results.append((name, status, detail))
    print(f"[{status}] {name} {detail}")


def db_get_latest_otp(username):
    conn = psycopg2.connect(DB_DSN)
    cur = conn.cursor()
    cur.execute(
        """
        SELECT otp_hash, expires_at, is_used FROM otp_codes
        WHERE user_id = (SELECT user_id FROM users WHERE username = %s)
        ORDER BY created_at DESC LIMIT 1
        """,
        (username,),
    )
    row = cur.fetchone()
    conn.close()
    return row


def db_count(query, params=None):
    conn = psycopg2.connect(DB_DSN)
    cur = conn.cursor()
    cur.execute(query, params or ())
    row = cur.fetchone()
    conn.close()
    return row[0]


def get_last_delivered_otp_from_log():
    """DevConsoleOTPProvider logs the OTP — this is the ONLY place it's readable,
    exactly as documented (dev-only mechanism)."""
    with open("/tmp/uvicorn_phase2_test.log") as f:
        lines = f.readlines()
    for line in reversed(lines):
        if "[DEV-ONLY OTP DELIVERY]" in line:
            # format: ... user=<username> otp=<code> ...
            parts = line.strip().split()
            otp = [p for p in parts if p.startswith("otp=")][0].split("=")[1]
            return otp
    return None


client = httpx.Client(base_url=BASE_URL, timeout=10)

# ---------- 1. Valid username/password ----------
resp = client.post("/auth/login", json={"username": "admin1", "password": "AdminPass123!"})
check("1. Valid username/password", resp.status_code == 200 and "pre_auth_token" in resp.json(), f"status={resp.status_code}")
pre_auth_token_admin = resp.json().get("pre_auth_token")

# ---------- 2. Invalid username ----------
resp = client.post("/auth/login", json={"username": "no_such_user", "password": "whatever"})
check("2. Invalid username", resp.status_code == 401, f"status={resp.status_code} body={resp.json()}")

# ---------- 3. Invalid password ----------
resp = client.post("/auth/login", json={"username": "admin1", "password": "WrongPassword!"})
check("3. Invalid password", resp.status_code == 401, f"status={resp.status_code} body={resp.json()}")
# Also confirm the error message doesn't reveal which field was wrong (same message as test 2)
resp2 = client.post("/auth/login", json={"username": "no_such_user", "password": "whatever"})
check(
    "3b. Error message identical for bad username vs bad password (no info leak)",
    resp.json()["error"]["message"] == resp2.json()["error"]["message"],
)

# ---------- 4. OTP generation ----------
otp_row = db_get_latest_otp("admin1")
check("4. OTP generation (otp_codes row created)", otp_row is not None, f"row={otp_row}")

otp_code = get_last_delivered_otp_from_log()
check("4b. OTP retrievable via dev-only delivery log", otp_code is not None, f"otp={otp_code}")

# ---------- 5. Valid OTP ----------
resp = client.post("/auth/otp/verify", json={"pre_auth_token": pre_auth_token_admin, "otp_code": otp_code})
check("5. Valid OTP -> JWT issued", resp.status_code == 200 and "access_token" in resp.json(), f"status={resp.status_code}")
admin_access_token = resp.json().get("access_token")
admin_role = resp.json().get("role")
check("5b. Correct role claim returned", admin_role == "Admin", f"role={admin_role}")

# ---------- 6. Invalid OTP ----------
resp2 = client.post("/auth/login", json={"username": "admin1", "password": "AdminPass123!"})
pre_auth_token_2 = resp2.json()["pre_auth_token"]
resp = client.post("/auth/otp/verify", json={"pre_auth_token": pre_auth_token_2, "otp_code": "000000"})
check("6. Invalid OTP rejected", resp.status_code == 401, f"status={resp.status_code}")

# ---------- 7. Expired OTP ----------
# Force-expire the OTP directly in DB (fast test, matches OTP_EXPIRE_SECONDS behaviour)
conn = psycopg2.connect(DB_DSN)
cur = conn.cursor()
cur.execute(
    "UPDATE otp_codes SET expires_at = NOW() - INTERVAL '1 minute' WHERE user_id = (SELECT user_id FROM users WHERE username='admin1') AND is_used = false"
)
conn.commit()
conn.close()
otp_code_2 = get_last_delivered_otp_from_log()  # the OTP value for resp2's login
resp = client.post("/auth/otp/verify", json={"pre_auth_token": pre_auth_token_2, "otp_code": otp_code_2})
check("7. Expired OTP rejected", resp.status_code == 401, f"status={resp.status_code}")

# ---------- 8. Reused OTP ----------
resp3 = client.post("/auth/login", json={"username": "admin1", "password": "AdminPass123!"})
pre_auth_token_3 = resp3.json()["pre_auth_token"]
otp_code_3 = get_last_delivered_otp_from_log()
first_use = client.post("/auth/otp/verify", json={"pre_auth_token": pre_auth_token_3, "otp_code": otp_code_3})
second_use = client.post("/auth/otp/verify", json={"pre_auth_token": pre_auth_token_3, "otp_code": otp_code_3})
check(
    "8. Reused OTP rejected on second attempt",
    first_use.status_code == 200 and second_use.status_code == 401,
    f"first={first_use.status_code} second={second_use.status_code}",
)

# ---------- 9. JWT generation ----------
decoded = pyjwt.decode(admin_access_token, JWT_SECRET, algorithms=["HS256"])
check("9. JWT generation (decodable, correct claims)", decoded.get("purpose") == "access" and decoded.get("role") == "Admin", f"claims={decoded}")

# ---------- 10. Valid JWT ----------
resp = client.get("/auth/me", headers={"Authorization": f"Bearer {admin_access_token}"})
check("10. Valid JWT accepted (GET /auth/me)", resp.status_code == 200 and resp.json()["username"] == "admin1", f"status={resp.status_code}")

# ---------- 11. Expired JWT ----------
expired_payload = decoded.copy()
import datetime
expired_payload["exp"] = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=1)
expired_token = pyjwt.encode(expired_payload, JWT_SECRET, algorithm="HS256")
resp = client.get("/auth/me", headers={"Authorization": f"Bearer {expired_token}"})
check("11. Expired JWT rejected", resp.status_code == 401, f"status={resp.status_code}")

# ---------- 12. Tampered JWT ----------
tampered_token = admin_access_token[:-5] + "AAAAA"
resp = client.get("/auth/me", headers={"Authorization": f"Bearer {tampered_token}"})
check("12. Tampered JWT rejected", resp.status_code == 401, f"status={resp.status_code}")

# ---------- 13. Missing JWT ----------
resp = client.get("/auth/me")
check("13. Missing JWT rejected", resp.status_code == 401, f"status={resp.status_code}")

# ---------- 14 & 16. Examination Centre login (needed for role tests) ----------
resp = client.post("/auth/login", json={"username": "centre1", "password": "CentrePass123!"})
pre_auth_centre = resp.json()["pre_auth_token"]
otp_centre = get_last_delivered_otp_from_log()
resp = client.post("/auth/otp/verify", json={"pre_auth_token": pre_auth_centre, "otp_code": otp_centre})
centre_access_token = resp.json()["access_token"]
check("14-setup. Examination Centre user login succeeded", resp.status_code == 200, f"status={resp.status_code}")

# ---------- 14. Unauthorized role (Examination Centre hitting Admin-only endpoint) ----------
resp = client.post("/admin/centres", headers={"Authorization": f"Bearer {centre_access_token}"})
check("14. Unauthorized role rejected (403)", resp.status_code == 403, f"status={resp.status_code}")

# ---------- 15. Authorized role (Admin hitting Admin-only endpoint -> reaches 501 scaffold, proving RBAC passed) ----------
resp = client.post("/admin/centres", headers={"Authorization": f"Bearer {admin_access_token}"})
check("15. Authorized role passes RBAC (reaches 501 scaffold, not 403/401)", resp.status_code == 501, f"status={resp.status_code}")

# ---------- 16. Examination-centre authorization (paper_authorizations check) ----------
import sys
sys.path.insert(0, ".")
from app.database import SessionLocal
from app.models import Paper, PaperAuthorization, ExamCentre, User
from app.services.authorization_service import is_centre_authorized_for_paper
from datetime import datetime, timezone, timedelta

db = SessionLocal()
admin_user = db.query(User).filter(User.username == "admin1").first()
centre = db.query(ExamCentre).filter(ExamCentre.centre_name == "Test Centre A").first()
paper = Paper(
    subject="Test Subject",
    file_reference="dummy.enc",
    sha256_hash="a" * 64,
    release_timestamp=datetime.now(timezone.utc) + timedelta(hours=1),
    registered_by=admin_user.user_id,
)
db.add(paper)
db.commit()

not_yet_authorized = is_centre_authorized_for_paper(db, centre.centre_id, paper.paper_id)
check("16a. Centre NOT authorized before an authorization row exists", not_yet_authorized is False)

auth_row = PaperAuthorization(
    paper_id=paper.paper_id, centre_id=centre.centre_id, authorized_by=admin_user.user_id, authorized_at=datetime.now(timezone.utc)
)
db.add(auth_row)
db.commit()
now_authorized = is_centre_authorized_for_paper(db, centre.centre_id, paper.paper_id)
check("16b. Centre authorized after paper_authorizations row created", now_authorized is True)

auth_row.is_revoked = True
db.commit()
revoked_check = is_centre_authorized_for_paper(db, centre.centre_id, paper.paper_id)
check("16c. Revoked authorization correctly denies access", revoked_check is False)

# cleanup
db.delete(auth_row)
db.delete(paper)
db.commit()
db.close()

# ---------- 17. Authentication failure logging ----------
failed_login_count = db_count("SELECT COUNT(*) FROM security_events WHERE event_type = 'FAILED_LOGIN'")
invalid_otp_count = db_count("SELECT COUNT(*) FROM security_events WHERE event_type = 'INVALID_OTP'")
audit_success_count = db_count("SELECT COUNT(*) FROM audit_events WHERE event_type = 'AUTH_SUCCESS'")
check("17. Authentication failure logging (security_events populated)", failed_login_count >= 2 and invalid_otp_count >= 1, f"failed_login={failed_login_count} invalid_otp={invalid_otp_count}")
check("17b. Successful-auth audit events recorded", audit_success_count >= 1, f"audit_success={audit_success_count}")

# ---------- 18. Secrets not appearing in API responses/logs ----------
all_bodies = [r.text for r in [resp]]
leak_found = False
with open("/tmp/uvicorn_phase2_test.log") as f:
    log_content = f.read()
if "AdminPass123!" in log_content or "CentrePass123!" in log_content or JWT_SECRET in log_content:
    leak_found = True
check("18. No plaintext password or JWT secret in server logs", not leak_found)

# Confirm password_hash is never returned by /auth/me
resp = client.get("/auth/me", headers={"Authorization": f"Bearer {admin_access_token}"})
check("18b. /auth/me response contains no password/hash field", "password" not in resp.text.lower())

# ---------- Logout test (bonus, part of the flow) ----------
resp = client.post("/auth/logout", headers={"Authorization": f"Bearer {admin_access_token}"})
check("Logout succeeds with valid JWT", resp.status_code == 200, f"status={resp.status_code}")
resp = client.get("/auth/me", headers={"Authorization": f"Bearer {admin_access_token}"})
check("Token rejected after logout (session revoked)", resp.status_code == 401, f"status={resp.status_code}")

# ---------- Summary ----------
print("\n" + "=" * 60)
passed = sum(1 for _, s, _ in results if s == "PASS")
total = len(results)
print(f"RESULT: {passed}/{total} PASSED")
for name, status, detail in results:
    if status == "FAIL":
        print(f"  FAILED: {name} {detail}")
