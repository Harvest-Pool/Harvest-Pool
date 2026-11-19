"""Safely archive the entire local dev database and produce photos, then start fresh.
Only run after stopping Flask, and only when you want to reset ALL local accounts.
"""
from pathlib import Path
from datetime import datetime
import shutil
import sys
ROOT = Path(__file__).resolve().parents[1]
db = ROOT / 'harvest_pool.db'
photos = ROOT / 'instance' / 'produce_photos'
print('This will archive and reset ALL LOCAL accounts, seller approvals, listings,')
print('orders, and Paystack TEST payment records. Real payments are not reversed.')
if input('Type RESET HARVEST POOL exactly to continue: ').strip() != 'RESET HARVEST POOL':
    print('Cancelled. No files were changed.'); sys.exit(0)
folder=ROOT/'backups'/('fresh_start_'+datetime.now().strftime('%Y%m%d_%H%M%S'))
folder.mkdir(parents=True, exist_ok=False)
if db.exists():
    shutil.move(str(db), str(folder/'harvest_pool.db'))
for suffix in ('-wal','-shm'):
    leftover=Path(str(db)+suffix)
    if leftover.exists(): shutil.move(str(leftover), str(folder/leftover.name))
if photos.exists(): shutil.move(str(photos), str(folder/'produce_photos'))
print('Archived old records at:', folder)
print('Now run python app.py, then python -m flask --app app create-admin.')
