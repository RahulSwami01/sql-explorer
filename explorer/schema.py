from django.core.cache import cache
from django.db import ProgrammingError

from explorer.app_settings import (
    EXPLORER_SCHEMA_EXCLUDE_TABLE_PREFIXES,
    EXPLORER_SCHEMA_INCLUDE_TABLE_PREFIXES, EXPLORER_SCHEMA_INCLUDE_VIEWS,
)
from explorer.tasks import build_schema_cache_async
from explorer.utils import InvalidExplorerConnectionException


# These wrappers make it easy to mock and test
def _get_includes():
    return EXPLORER_SCHEMA_INCLUDE_TABLE_PREFIXES


def _get_excludes():
    return EXPLORER_SCHEMA_EXCLUDE_TABLE_PREFIXES


def _include_views():
    return EXPLORER_SCHEMA_INCLUDE_VIEWS is True


def _include_table(t):
    if _get_includes() is not None:
        return any([t.startswith(p) for p in _get_includes()])
    return not any([t.startswith(p) for p in _get_excludes()])


def connection_schema_cache_key(connection_id):
    return f"_explorer_cache_key_{connection_id}"


def connection_schema_json_cache_key(connection_id):
    return f"_explorer_cache_key_json_{connection_id}"


def transform_to_json_schema(schema_info):
    json_schema = {}
    for table_name, columns in schema_info:
        json_schema[table_name] = []
        for column_name, _ in columns:
            json_schema[table_name].append(column_name)
    return json_schema


def schema_json_info(db_connection):
    key = connection_schema_json_cache_key(db_connection.id)
    ret = cache.get(key)
    if ret:
        return ret
    try:
        si = schema_info(db_connection) or []
    except InvalidExplorerConnectionException:
        return []
    json_schema = transform_to_json_schema(si)
    cache.set(key, json_schema)
    return json_schema


def schema_info(db_connection):
    key = connection_schema_cache_key(db_connection.id)
    ret = cache.get(key)
    if ret:
        return ret
    else:
        return build_schema_cache_async(db_connection.id)


def clear_schema_cache(db_connection):
    key = connection_schema_cache_key(db_connection.id)
    cache.delete(key)

    key = connection_schema_json_cache_key(db_connection.id)
    cache.delete(key)

def build_schem_info_manual():
    # Get the path to the current script's directory
    current_dir = Path(__file__).parent

    # Construct the full path to the file
    #file_path = current_dir / 'my_file.txt'
    #please clean schema file, keep simple create statements.
    file_path = current_dir / 'schema.sql'
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            sql_script = f.read()
    except FileNotFoundError:
        print(f"Error: The file '{file_path}' was not found.")
        sql_script = None
    except Exception as e:
        print(f"An error occurred while reading the file: {e}")
        sql_script = None
    parser = DDLParser(sql_script)
    parse_results = parser.run()
    ##print(len(parse_results))
    # The result is typically a list of dictionaries, one for each parsed DDL statement.
    # For a single CREATE TABLE, it will be a list with one dictionary.
    ret=[]
    if parse_results:
        for i in range(len(parse_results)):
            table_schema = parse_results[i]
            print(f"Table Name: {table_schema.get('table_name')}")
            #print("Columns:")
            td = []
            for column in table_schema.get('columns', []):
                td.append((column.get('name'), column.get('type')))
                ##print(f"  - Name: {column.get('name')}, Type: {column.get('type')}, Nullable: {column.get('nullable')}")
            #print(f"Primary Key: {table_schema.get('primary_key')}")
            ret.append((table_schema.get('table_name'), td))
    return ret
    
def build_schema_info(db_connection):
    """
        Construct schema information via engine-specific queries of the
        tables in the DB.

        :return: Schema information of the following form,
                 sorted by db_table_name.
            [
                ("db_table_name",
                    [
                        ("db_column_name", "DbFieldType"),
                        (...),
                    ]
                )
            ]

        """
    connection = db_connection.as_django_connection()
    ## Code for Manual adding schema, Its for large database having 1000 tables. you must use manual otherwise you will put your database server in trouble.
    if str(type(connection))!="<class 'mssql.base.DatabaseWrapper'>":
        print("Database is too big, So return Null")
        
        return build_schem_info_manual()
    ret = []
    with connection.cursor() as cursor:
        tables_to_introspect = connection.introspection.table_names(
            cursor, include_views=_include_views()
        )

        for table_name in tables_to_introspect:
            if not _include_table(table_name):
                continue
            try:
                table_description = connection.introspection.get_table_description(
                    cursor, table_name
                )
            # Issue 675. A connection maybe not have permissions to access some tables in the DB.
            except ProgrammingError:
                continue

            td = []
            for row in table_description:
                column_name = row[0]
                try:
                    field_type = connection.introspection.get_field_type(
                        row[1], row
                    )
                except KeyError:
                    field_type = "Unknown"
                td.append((column_name, field_type))
            ret.append((table_name, td))
    return ret


