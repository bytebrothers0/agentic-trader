import os

html = open(os.path.join(os.environ["APPDATA"], "MetaQuotes", "Terminal",
                         "D0E8209F77C8CF37AD8BF550E51FF075", "MSNR_Alchemist_report.htm"),
            encoding="utf-8", errors="ignore").read()
i = html.find("Initial Deposit")
print(repr(html[max(0, i - 200): i + 300]))
i2 = html.find("Total Net Profit")
print(repr(html[max(0, i2 - 100): i2 + 250]))
