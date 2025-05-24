import polars as pl


def get_column_names_from_df(df: pl.DataFrame) -> list[str]:
    """
    Extracts column names from a Polars DataFrame.

    Args:
        df: The Polars DataFrame.

    Returns:
        A list of column name strings.
    """
    return df.columns


def get_schema_from_df(df: pl.DataFrame) -> dict[str, str]:
    """
    Extracts the schema (column names and their Polars types as strings)
    from a Polars DataFrame.

    Args:
        df: The Polars DataFrame.

    Returns:
        A dictionary mapping column names to their type strings.
    """
    return {col: str(dtype) for col, dtype in df.schema.items()}
