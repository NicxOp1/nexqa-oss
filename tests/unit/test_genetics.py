import pytest

from nexqa.genetics.gene_parser import gene_parser
from nexqa.genetics.gene_validator import Severity, gene_validator
from nexqa.genetics.prompt_builder import prompt_builder
from nexqa.models.gene_models import Gene, GeneSet, GeneType


def test_builder_creates_core_genes(example_spec_path):
    gene_set = prompt_builder.build(example_spec_path)
    types = {g.type for g in gene_set.genes}
    assert GeneType.IDENTITY in types
    assert GeneType.FLOW in types


def test_identity_is_always_immutable():
    gene = Gene(type=GeneType.IDENTITY, content="You are Ana.", immutable=False)
    assert gene.immutable is True


def test_serialize_parse_round_trip(example_spec_path):
    original = prompt_builder.build(example_spec_path)
    parsed = gene_parser.parse(original.serialize())

    assert [g.type for g in parsed.genes] == [g.type for g in original.genes]
    for before, after in zip(original.genes, parsed.genes):
        assert after.immutable == before.immutable
        assert after.max_mutations == before.max_mutations


def test_untagged_prompt_falls_back_to_identity():
    gene_set = gene_parser.parse("You are Ana, a receptionist. Be kind.")
    assert len(gene_set.genes) == 1
    assert gene_set.genes[0].type == GeneType.IDENTITY


def test_built_spec_has_no_validation_errors(example_spec_path):
    issues = gene_validator.validate(prompt_builder.build(example_spec_path))
    assert not [i for i in issues if i.severity == Severity.ERROR]


def test_replacing_immutable_gene_is_rejected():
    gene_set = GeneSet(
        genes=[
            Gene(type=GeneType.IDENTITY, content="You are Ana."),
            Gene(type=GeneType.FLOW, content="Greet, then ask for the date."),
        ]
    )
    with pytest.raises(ValueError):
        gene_parser.replace_gene(gene_set, GeneType.IDENTITY, "You are Bob.")

    updated = gene_parser.replace_gene(gene_set, GeneType.FLOW, "Greet first.")
    assert updated.get_gene(GeneType.FLOW).content == "Greet first."
