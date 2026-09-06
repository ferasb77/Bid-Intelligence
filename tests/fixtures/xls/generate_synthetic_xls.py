"""Developer-only generator for synthetic_legacy.xls.

Requires xlwt, which is intentionally not a production or test dependency.
The generated binary is committed so normal tests only need the xlrd reader.
"""
from datetime import datetime
from pathlib import Path

import xlwt


def main():
    output = Path(__file__).with_name("synthetic_legacy.xls")
    book = xlwt.Workbook(encoding="utf-8")

    data = book.add_sheet("Main Data")
    data.write_merge(0, 0, 0, 3, "Commercial Response")
    data.write(9, 0, "Café – أسعار")
    data.write(9, 1, 42)
    data.write(9, 2, 12.5)
    data.write(9, 3, False)
    data.write(10, 0, 0)
    data.write(11, 0, 0.25, xlwt.easyxf(num_format_str="0%"))
    data.write(12, 0, 0.125, xlwt.easyxf(num_format_str="0.0%"))
    data.write(13, 0, datetime(2028, 2, 29), xlwt.easyxf(num_format_str="YYYY-MM-DD"))
    data.write(14, 0, datetime(2028, 2, 29, 13, 45, 30), xlwt.easyxf(num_format_str="YYYY-MM-DD hh:mm:ss"))
    data.write(15, 0, xlwt.Formula("B10+C10"))

    hidden = book.add_sheet("Hidden Guidance")
    hidden.visibility = 1
    hidden.write(0, 0, "Internal instruction retained")

    very_hidden = book.add_sheet("Very Hidden")
    very_hidden.visibility = 2
    very_hidden.write(0, 0, "Very hidden evidence")

    book.add_sheet("Empty Sheet")
    book.save(str(output))


if __name__ == "__main__":
    main()
