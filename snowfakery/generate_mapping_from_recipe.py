import typing as T
from collections import defaultdict


from snowfakery.data_generator import ExecutionSummary
from snowfakery.salesforce import find_record_type_column
from snowfakery.data_generator_runtime import Dependency
from snowfakery.utils.collections import OrderedSet

from .cci_mapping_files.declaration_parser import SObjectRuleDeclaration
from .cci_mapping_files.post_processes import add_after_statements


# TODO: Could this be merged with Execution Summary?
class ExecutionSummaryAndDeclarations(T.NamedTuple):
    sorted_tables: T.Mapping
    reference_fields: T.Mapping[T.Tuple, str]
    declarations: T.Mapping[str, SObjectRuleDeclaration]


def mapping_from_recipe_templates(
    summary: ExecutionSummary,
    declarations: T.Mapping[str, SObjectRuleDeclaration] = None,
):
    """Use the outputs of the recipe YAML and convert to Mapping.yml format"""
    organized_exec_summary = organize_by_dependencies(summary, declarations)
    mappings = mappings_from_sorted_tables(organized_exec_summary)
    return mappings


# TODO: Could be a method on ExecutionSummary
def organize_by_dependencies(
    summary: ExecutionSummary,
    declarations: T.Optional[T.Mapping[str, SObjectRuleDeclaration]],
) -> ExecutionSummaryAndDeclarations:
    declarations = declarations or {}
    relevant_declarations = [decl for decl in declarations.values() if decl.load_after]

    inferred_dependencies, declared_dependencies, reference_fields = build_dependencies(
        summary.intertable_dependencies, relevant_declarations
    )
    tables = summary.tables.copy()
    remove_person_contact_id(inferred_dependencies, tables)
    table_order = sort_dependencies(
        inferred_dependencies, declared_dependencies, tables
    )
    sorted_tables = {tablename: tables[tablename] for tablename in table_order}
    return ExecutionSummaryAndDeclarations(
        sorted_tables, reference_fields, declarations
    )


def remove_person_contact_id(dependencies, tables):
    if "Account" in dependencies:
        dep_to_person_contact = [
            dep
            for dep in dependencies["Account"]
            if dep.table_name_to.lower() == "personcontact"
        ]
        for dep in dep_to_person_contact:
            dependencies["Account"].remove(dep)

    if tables.get("Account") and tables["Account"].fields.get("PersonContactId"):
        del tables["Account"].fields["PersonContactId"]


def build_dependencies(
    intertable_dependencies,
    declarations: T.Sequence[SObjectRuleDeclaration] = None,
):
    """Figure out which tables depend on which other ones (through foreign keys)

    intertable_dependencies is a dict with values of Dependency objects.

    Returns two things:
        1. a dictionary allowing easy lookup of dependencies by parent table
        2. a dictionary allowing lookups by (tablename, fieldname) pairs
    """
    inferred_dependencies = defaultdict(OrderedSet)
    declared_dependencies = defaultdict(OrderedSet)
    reference_fields = {}
    declarations = declarations or ()

    for dep in intertable_dependencies:
        table_deps = inferred_dependencies[dep.table_name_from]
        table_deps.add(dep)
        reference_fields[(dep.table_name_from, dep.field_name)] = dep.table_name_to
    for decl in declarations:
        assert isinstance(decl.load_after, list)
        for target in decl.load_after:
            declared_dependencies[decl.sf_object].add(
                Dependency(decl.sf_object, target, "(none)")
            )

    return inferred_dependencies, declared_dependencies, reference_fields


def _table_is_free(table_name, dependencies, sorted_tables):
    """Check if every child of this table is already sorted

    Look at the unit test test_table_is_free_simple to see some
    usage examples.
    """
    tables_this_table_depends_upon = dependencies.get(table_name, OrderedSet()).copy()
    for dependency in sorted(tables_this_table_depends_upon):
        if (
            dependency.table_name_to in sorted_tables
            or dependency.table_name_to == table_name
        ):
            tables_this_table_depends_upon.remove(dependency)

    return len(tables_this_table_depends_upon) == 0


def sort_dependencies(inferred_dependencies, declared_dependencies, tables) -> T.List:
    """Sort the dependencies to output tables in the right order."""
    dependencies = {**inferred_dependencies, **declared_dependencies}
    sorted_tables = []

    while tables:
        remaining = len(tables)
        leaf_tables = [
            table
            for table in tables
            if _table_is_free(table, dependencies, sorted_tables)
        ]
        sorted_tables.extend(leaf_tables)
        tables = [table for table in tables if table not in sorted_tables]
        if len(tables) == remaining:

            # this is a bit tricky.
            # run the algorithm with ONLY the declared
            # dependencies and see if it comes to resolution
            if inferred_dependencies and declared_dependencies:
                subset = sort_dependencies({}, declared_dependencies, tables.copy())
                sorted_tables.extend(subset)
            else:
                sorted_tables.append(sorted(tables)[0])

    return sorted_tables


def mappings_from_sorted_tables(exec_summary: ExecutionSummaryAndDeclarations):
    """Generate mapping.yml data structures."""
    tables = exec_summary.sorted_tables
    reference_fields = exec_summary.reference_fields
    declarations = exec_summary.declarations

    mappings = {}
    for table_name, table in tables.items():
        record_type_col = find_record_type_column(table_name, table.fields.keys())

        fields = {
            fieldname: fieldname
            for fieldname, fielddef in table.fields.items()
            if (table_name, fieldname) not in reference_fields.keys()
            and fieldname != record_type_col
        }
        if record_type_col:
            fields["RecordTypeId"] = record_type_col

        lookups = {
            fieldname: {
                "table": reference_fields[(table_name, fieldname)],
                "key_field": fieldname,
            }
            for fieldname, fielddef in table.fields.items()
            if (table_name, fieldname) in reference_fields.keys()
        }
        if table_name == "PersonContact":
            sf_object = "Contact"
        else:
            sf_object = table.name
        mapping = {"sf_object": sf_object, "table": table.name, "fields": fields}
        if lookups:
            mapping["lookups"] = lookups

        sobject_declarations = declarations.get(table_name)
        if sobject_declarations:
            mapping.update(sobject_declarations.as_mapping())

        mappings[f"Insert {table_name}"] = mapping

    add_after_statements(mappings)
    return mappings


def _table_to_template(table_name, table, organized_exec_summary):
    reference_fields = organized_exec_summary.reference_fields

    def field_to_pair(field_name):
        if (table_name, field_name) in reference_fields:
            return {"reference": reference_fields[(table_name, field_name)]}
        else:
            return "${{current_row.%s}}" % field_name

    for_each = {
        "var": "current_row",
        "value": {"Dataset.iterate": {"dataset": f"{table_name}.csv"}},
    }

    fields = {fieldname: field_to_pair(fieldname) for fieldname in table.fields}
    return {"object": table_name, "for_each": for_each, "fields": fields}


def generate_data_description_recipe_recipe_templates(
    summary: ExecutionSummary,
    declarations: T.Mapping[str, SObjectRuleDeclaration] = None,
):
    organized_exec_summary = organize_by_dependencies(summary, declarations)
    templates = [
        _table_to_template(table_name, table, organized_exec_summary)
        for table_name, table in organized_exec_summary.sorted_tables.items()
    ]
    return [{"plugin": "snowfakery.standard_plugins.datasets.Dataset"}] + templates
