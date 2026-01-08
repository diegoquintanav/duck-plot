import sys
from pathlib import Path
from typing import Optional

import altair as alt
import duckdb
import pandas as pd
import typer
from typing_extensions import Annotated

__version__ = "0.1.0"

app = typer.Typer()

def create_visualization(df: pd.DataFrame, x_column: str, y_column: str, chart_type: str) -> alt.Chart:
    """Create either a line or bar chart based on user input"""
    if chart_type == "line":
        chart = alt.Chart(df).mark_line().encode(
            x=x_column,
            y=y_column,
            tooltip=[x_column, y_column]
        )
    else:  # bar chart
        chart = alt.Chart(df).mark_bar().encode(
            x=x_column,
            y=y_column,
            tooltip=[x_column, y_column]
        )
    
    return chart.properties(
        width=800,
        height=400,
        title=f"{y_column} vs {x_column}"
    )

def pd_to_rich_tbl(df: pd.DataFrame) -> None:
    from rich.console import Console
    from rich.table import Table
    console = Console()
    table = Table(title="Query Results")
    for col in df.columns:
        if df[col].dtype != object:
            table.add_column(col, justify="right", style='green')
        else:
            table.add_column(col)
    for _, row in df.iterrows():
        table.add_row(*[str(val) for val in row])
    console.print(table)

@app.command()
def visualize(
    csv: Annotated[Optional[Path], typer.Argument(help="Path to CSV file to load into DuckDB")] = None,
    query: Annotated[Optional[str], typer.Option("--query", "-q", help="SQL query to execute. If None, a SELECT * will be executed")] = None,
    x_column: Annotated[Optional[str], typer.Option("--x", "-x", help="Column name for X-axis")] = None,
    y_column: Annotated[Optional[str], typer.Option("--y", "-y", help="Column name for Y-axis")] = None,
    chart_type: Annotated[str, typer.Option(
        "--type", 
        "-t", 
        help="Type of chart (line or bar)",
        callback=lambda x: x.lower()
    )] = "line",
    db_file: Annotated[Optional[str], typer.Option(
        "--db",
        "-d",
        help="Path to DuckDB database file (optional)"
    )] = None,
    query_only: Annotated[bool, typer.Option(
        "--query-only",
        help="Output query results to stdout and skip chart creation"
    )] = False,
    limit: Annotated[Optional[int], typer.Option(
        "--limit",
        "-l",
        help="Limit number of rows returned by default query (optional)"
    )] = None,
    show_columns_only: Annotated[bool, typer.Option(
        "--show-columns-only",
        help="Show available columns from the CSV file and exit"
    )] = False,
):
    """
    Execute SQL query from stdin or from argument, create visualization from results and display it in the browser.
    If no database file is specified, an in-memory database will be used.
    """

    if show_columns_only:
        if not csv:
            typer.echo("Error: --show-columns-only requires a CSV file to be specified with the 'csv' argument", err=True)
            raise typer.Exit(1)
        try:
            conn = duckdb.connect(':memory:')
            conn.execute(f"CREATE TABLE data AS SELECT * FROM read_csv_auto('{csv}')")
            columns = conn.execute("PRAGMA table_info('data')").df()
            typer.echo("Available columns in the CSV file:")
            for col in columns['name']:
                typer.echo(f"- {col}")
        except Exception as e:
            typer.echo(f"Error reading CSV file: {str(e)}", err=True)
            raise typer.Exit(1)
        finally:
            if 'conn' in locals():
                conn.close()
        raise typer.Exit(0)

    try:
        # Check for input from pipe
        if not sys.stdin.isatty():
            query_input = sys.stdin.read().strip()
        else:
            query_input = None

        # Prioritize stdin over argument if both are provided
        final_query = query_input if query_input else query
        default_query = f"SELECT * FROM read_csv_auto('{csv}')" if csv else None

        if final_query is None and default_query:
            if limit is not None:
                default_query += f" LIMIT {limit}"
            final_query = default_query
            typer.echo("No query provided, using default query:", err=True)
            typer.echo(default_query, err=True)

        if not final_query:
            typer.echo("Error: No file or SQL query provided.", err=True)
            typer.echo("Examples:", err=True)
            typer.echo("  python script.py table.csv -x date -y value", err=True)
            typer.echo("  python script.py -q 'SELECT * FROM table' -x date -y value", err=True)
            typer.echo("  echo 'SELECT * FROM table' | python script.py -x date -y value", err=True)
            raise typer.Exit(1)
        # Connect to DuckDB
        try:
            conn = duckdb.connect(db_file if db_file else ':memory:')
            typer.echo(f"Connected to {'database: ' + db_file if db_file else 'in-memory database'}", err=True)
        except Exception as e:
            typer.echo(f"Error connecting to database: {str(e)}", err=True)
            raise typer.Exit(1)
            
        # Execute query and get results as  DataFrame
        try:
            df = conn.execute(final_query).df()
        except Exception as e:
            typer.echo(f"Error executing query: {str(e)}", err=True)
            raise typer.Exit(1)
            
        if df.empty:
            typer.echo("Error: Query returned no results", err=True)
            raise typer.Exit(1)

        if query_only:
            # Output results to stdout
            typer.echo(pd_to_rich_tbl(df), err=True)
            return

        # Validate chart parameters if we're creating a visualization
        if x_column is None or y_column is None:
            typer.echo("Error: Both --x and --y options are required for chart creation", err=True)
            raise typer.Exit(1)

        if chart_type not in ["line", "bar"]:
            typer.echo(f"Error: Chart type must be 'line' or 'bar', not '{chart_type}'", err=True)
            raise typer.Exit(1)
            
        # Validate column names
        if x_column not in df.columns:
            typer.echo(f"Error: Column '{x_column}' not found in query results", err=True)
            typer.echo(f"Available columns: {', '.join(df.columns)}", err=True)
            raise typer.Exit(1)
        if y_column not in df.columns:
            typer.echo(f"Error: Column '{y_column}' not found in query results", err=True)
            typer.echo(f"Available columns: {', '.join(df.columns)}", err=True)
            raise typer.Exit(1)
            
        # Create visualization
        chart = create_visualization(df, x_column, y_column, chart_type)
        alt.renderers.enable('browser')
        chart.show()
        typer.echo(f"Successfully created {chart_type} chart!", err=True)
        
    except Exception as e:
        typer.echo(f"Error: {str(e)}", err=True)
        raise typer.Exit(1)
    finally:
        if 'conn' in locals():
            conn.close()

if __name__ == "__main__":
    app()
