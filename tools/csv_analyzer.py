# csv_analyzer.py

import csv
import os
import statistics
import threading


def analyze_csv(filepath: str, timeout: int = 10) -> dict:
    """
    Analyze a CSV file and return structured summary.

    Args:
        filepath: path to the CSV file to analyze.
        timeout: maximum time in seconds to allow for analysis.

    Returns:
        dict with:
        - success
        - summary
        - columns
        - sample_rows
        - error
    """

    if not filepath or not filepath.strip():
        return {
            "success": False,
            "summary": {},
            "columns": [],
            "sample_rows": [],
            "error": "No file path provided"
        }

    filepath = filepath.strip()

    if not os.path.exists(filepath):
        return {
            "success": False,
            "summary": {},
            "columns": [],
            "sample_rows": [],
            "error": f"File not found: {filepath}"
        }

    if not filepath.lower().endswith(".csv"):
        return {
            "success": False,
            "summary": {},
            "columns": [],
            "sample_rows": [],
            "error": f"File is not a CSV: {filepath}"
        }


    result = {}
    error_holder = {}


    def analyze():

        try:
            rows = []

            with open(
                filepath,
                "r",
                newline="",
                encoding="utf-8"
            ) as csvfile:

                reader = csv.DictReader(csvfile)

                columns = reader.fieldnames or []

                for row in reader:
                    rows.append(dict(row))


            # Empty CSV
            if not rows:
                result.update({
                    "success": True,
                    "summary": {
                        "row_count": 0,
                        "column_count": len(columns)
                    },
                    "columns": columns,
                    "sample_rows": [],
                    "error": None
                })

                return



            column_stats = {}


            for col in columns:

                values = [
                    row[col]
                    for row in rows
                    if row.get(col) not in (None, "")
                ]


                numeric_values = []


                for value in values:
                    try:
                        numeric_values.append(float(value))

                    except ValueError:
                        pass



                # Numeric column
                if numeric_values:

                    column_stats[col] = {
                        "type": "numeric",
                        "count": len(numeric_values),
                        "min": round(min(numeric_values), 4),
                        "max": round(max(numeric_values), 4),
                        "mean": round(
                            statistics.mean(numeric_values),
                            4
                        ),
                        "nulls": len(rows) - len(values)
                    }


                # Text/category column
                else:

                    unique_values = list(set(values))

                    column_stats[col] = {
                        "type": "categorical",
                        "count": len(values),
                        "unique": len(unique_values),
                        "top_values": unique_values[:5],
                        "nulls": len(rows) - len(values)
                    }



            result.update({

                "success": True,

                "summary": {
                    "row_count": len(rows),
                    "column_count": len(columns),
                    "column_stats": column_stats
                },

                "columns": columns,

                "sample_rows": rows[:3],

                "error": None
            })


        except PermissionError as e:

            error_holder["error"] = (
                f"Permission denied when reading file: {e}"
            )


        except UnicodeDecodeError as e:

            error_holder["error"] = (
                f"File encoding error: {e}"
            )


        except csv.Error as e:

            error_holder["error"] = (
                f"CSV parsing error: {e}"
            )


        except Exception as e:

            error_holder["error"] = str(e)



    # Run analysis in a thread
    thread = threading.Thread(
        target=analyze
    )

    thread.start()


    # Wait with timeout
    thread.join(timeout)


    # Timeout happened
    if thread.is_alive():

        return {
            "success": False,
            "summary": {},
            "columns": [],
            "sample_rows": [],
            "error": (
                f"CSV analysis timed out after {timeout} seconds"
            )
        }


    # Error happened
    if "error" in error_holder:

        return {
            "success": False,
            "summary": {},
            "columns": [],
            "sample_rows": [],
            "error": error_holder["error"]
        }


    return result