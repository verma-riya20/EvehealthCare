"""Create an admin user and a little demo data.  Run:  python -m app.seed  (safe to re-run)."""
from decimal import Decimal

from sqlalchemy import select

from app.config import settings
from app.database import Base, SessionLocal, engine
from app.models import Centre, CentreTest, DiagnosticTest, User
from app.security import hash_password

TESTS = {
    "Complete Blood Count": "Routine blood panel",
    "Lipid Profile": "Cholesterol and triglycerides",
    "HbA1c": "3-month average blood sugar",
    "Thyroid Profile (T3, T4, TSH)": "Thyroid function",
}
CENTRES = {
    ("EVE Diagnostics - Sector 62", "Noida"): {"Complete Blood Count": "350.00", "Lipid Profile": "600.00", "HbA1c": "450.00"},
    ("EVE Diagnostics - Connaught Place", "Delhi"): {"Complete Blood Count": "400.00", "Thyroid Profile (T3, T4, TSH)": "550.00"},
}


def main() -> None:
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        if not db.scalar(select(User).where(User.email == settings.admin_email)):
            db.add(User(email=settings.admin_email, full_name="Admin",
                        hashed_password=hash_password(settings.admin_password), is_admin=True))
        tests = {}
        for name, desc in TESTS.items():
            t = db.scalar(select(DiagnosticTest).where(DiagnosticTest.name == name))
            if not t:
                t = DiagnosticTest(name=name, description=desc)
                db.add(t)
            tests[name] = t
        db.flush()
        for (cname, loc), offered in CENTRES.items():
            c = db.scalar(select(Centre).where(Centre.name == cname, Centre.location == loc))
            if not c:
                c = Centre(name=cname, location=loc)
                db.add(c)
                db.flush()
                for tname, price in offered.items():
                    db.add(CentreTest(centre_id=c.id, test_id=tests[tname].id, price=Decimal(price)))
        db.commit()
    print(f"Seeded. Admin login: {settings.admin_email} / {settings.admin_password}")


if __name__ == "__main__":
    main()
