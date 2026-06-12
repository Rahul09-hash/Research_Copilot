import sys

file_path = "D:/Research_Copilot/web/app.css"

with open(file_path, "r", encoding="utf-8") as f:
    lines = f.readlines()

# The file is healthy up to line 825.
# Let's truncate everything after line 825 and append the correct CSS.
correct_tail = """/* Print Stylesheet for High-Fidelity PDF Export */
@media print {
  @page {
    margin: 1.5cm;
  }

  /* Hide all non-essential UI elements */
  .sidebar,
  .chat-head,
  .composer,
  .panel-head,
  .button-grid,
  .compare-box,
  .status,
  .nav,
  #pdfViewerPanel,
  .file-btn {
    display: none !important;
  }

  /* Reset layout constraints to allow clean multi-page printing */
  body,
  .main,
  .view.active {
    display: block !important;
    height: auto !important;
    overflow: visible !important;
    padding: 0 !important;
    background: white !important;
    grid-template-columns: 1fr !important;
  }

  .messages {
    overflow: visible !important;
    display: flex;
    flex-direction: column;
    gap: 15px;
    padding: 0 !important;
  }

  .message {
    break-inside: avoid;
    page-break-inside: avoid;
    max-width: 85%;
    border: 1px solid #dce3e8 !important;
    box-shadow: none !important;
    background: white !important;
    color: black !important;
  }

  .message.user {
    align-self: flex-end;
    background: #f0fdfa !important; /* very light teal */
    border-color: #ccfbf1 !important;
  }

  .message.assistant {
    align-self: flex-start;
  }

  .sources {
    break-inside: avoid;
  }
}
"""

with open(file_path, "w", encoding="utf-8") as f:
    f.writelines(lines[:825])
    f.write(correct_tail)

print("Fixed app.css successfully!")
