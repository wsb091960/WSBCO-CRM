CRM V3.6 ZIP 97420 County Auto-Select Fix v2

Install from /workspaces/WSBCO-CRM:
  unzip -o WSBCO_CRM_V3_6_ZIP_97420_Coos_Fix_v2.zip
  python install_v36_zip_fix_v2.py

Restart CRM, then hard-refresh comparison page (Ctrl+Shift+R).
Test: ZIP 97420 -> county Coos (automatically, without choosing the dropdown).

This is a targeted fix for ZIP 97420 only; other ZIPs still need county confirmation.
