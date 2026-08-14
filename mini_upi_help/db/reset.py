"""Standalone reset script — run directly, or import reset_database() from app.py."""
from db.schema import init_db

def reset_database():
    init_db(reset=True)
    return {"status": "reset", "message": "Database restored to original seed data."}

if __name__ == "__main__":
    result = reset_database()
    print(result["message"])