SVCE AI Assistant update: PDF/DOCX/image upload + chart visualization

This patch uses the latest V2.2 frontend and adds a FastAPI extraction endpoint.

Install steps:
1. Back up frontend/src/main.jsx, frontend/src/styles.css, api/main.py, and requirements.txt.
2. Copy frontend/src/main.jsx and styles.css into your project frontend/src/.
3. Merge the provided api/main.py endpoint/import/helper into your existing api/main.py. It is based on the uploaded main.py; if your local file contains newer changes, merge rather than overwrite.
4. Add requirements-additions.txt lines to your existing requirements.txt, then run: python -m pip install -r requirements.txt
5. Restart backend and frontend.

Supported upload: TXT, MD, CSV, JSON, text-based PDF, DOCX, PNG, JPG/JPEG, WEBP, up to 10 MB. PDF text extraction does not OCR scanned PDFs. Image OCR requires the Tesseract OCR desktop application installed and available on PATH, plus the Python packages in requirements-additions.txt. Files are processed in memory and not saved to disk.

Charts: The frontend retains the existing interactive visualization for numeric Markdown tables in assistant answers. Uploading CSV sends its extracted text to the assistant; ask it to summarize/compare the data in a table, then use Visualize table. This patch does not add XLSX upload or automatic arbitrary-data chart generation. Chart display does not independently verify factual accuracy.
