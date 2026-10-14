"""P-Agent reference example: analysis string + chart specs (emit_chart).

This file is for reference only. Do not import or run it—the code below is
meant to be copied into the P-Agent sandbox context, where the following are
pre-injected: df (pandas DataFrame) and the predefined functions: describe_df,
value_counts_column, chart_from_columns, head_df, info_df, emit_chart.

Reference script (runs only inside the sandbox):
----------------------------------------------
# 1) Shape and first rows (avoid leading with full info_df output — verbose)
print(f"=== Rows: {len(df)} ===")
print(head_df(df, 5))
print(describe_df(df))

# 2) Pick a column to count (use a real column name from df.columns)
col = "category" if "category" in df.columns else list(df.columns)[0] if len(df.columns) else None
if col:
    counts = value_counts_column(df, col)
    print(f"\\n=== Count by {col} ===")
    print(counts)
    chart_data = [{"label": str(k), "value": int(v)} for k, v in counts.items()]
    emit_chart({
        "type": "chart",
        "chart_type": "bar",
        "title": f"Count by {col}",
        "data": chart_data,
        "config": {"xAxis": col, "yAxis": "Count"},
    })

print("\\nDone.")
"""

# No executable code at module level—avoids NameError if this module is loaded.
