"""Keep controlled evaluation suppliers out of the reviewer worklist."""

import sqlalchemy as sa
from alembic import op

revision = "0022_evaluation_suppliers"
down_revision = "0021_composite_slots"
branch_labels = None
depends_on = None

# Exact synthetic name/contact pairs from the pinned 15-supplier evaluation corpus.
# Never match by company name alone or by an example.com email alone.
LEGACY_EVALUATION_IDENTITIES = (('Kaveri Flow Controls Private Limited', 'ananya.rao@example.com'),
 ('Norwood Clinical Systems Private Limited', 'rohan.kulkarni@example.com'),
 ('Prithvi Sustainable Packaging Private Limited', 'devika.shah@example.com'),
 ('Eastbridge Logistics and Warehousing Private Limited', 'souvik.banerjee@example.com'),
 ('Sahyadri Renewable Components Private Limited', 'neha.patil@example.com'),
 ('Mallige Precision Works Private Limited', 'evaluation.mallige_precision_works@example.com'),
 ('Narmada Instrumentation Private Limited', 'evaluation.narmada_instrumentation@example.com'),
 ('Aravali Process Equipment Private Limited', 'evaluation.aravali_process_equipment@example.com'),
 ('Coromandel Sensor Systems Private Limited', 'evaluation.coromandel_sensor_systems@example.com'),
 ('Tungabhadra Industrial Services Private Limited',
  'evaluation.tungabhadra_industrial_services@example.com'),
 ('Dakshin Freight Services Private Limited', 'evaluation.dakshin_logistics@example.com'),
 ('Amrutha Meal Services Private Limited', 'evaluation.amrutha_food@example.com'),
 ('Varsha Facilities Services Private Limited', 'evaluation.varsha_facilities@example.com'),
 ('Chitra Industrial Components Private Limited', 'evaluation.chitra_components@example.com'),
 ('Udaya Equipment Maintenance Private Limited', 'evaluation.udaya_maintenance@example.com'))


def upgrade() -> None:
    op.add_column("suppliers", sa.Column("is_evaluation", sa.Boolean(), server_default=sa.false(), nullable=False))
    suppliers = sa.table("suppliers", sa.column("name", sa.String()),
                         sa.column("contact_email", sa.String()), sa.column("country", sa.String()),
                         sa.column("account_id", sa.Uuid()), sa.column("category", sa.String()),
                         sa.column("subcategory", sa.String()), sa.column("is_evaluation", sa.Boolean()))
    # Evaluator-created rows have no portal account or selected application category.
    # Retain originals, statuses, reviews, IDs and results; only mark the known test records.
    op.execute(suppliers.update().where(
        suppliers.c.account_id.is_(None), suppliers.c.category.is_(None),
        suppliers.c.subcategory.is_(None), suppliers.c.country == "India",
        sa.or_(*(sa.and_(suppliers.c.name == name, suppliers.c.contact_email == email)
                 for name, email in LEGACY_EVALUATION_IDENTITIES)),
    ).values(is_evaluation=True))


def downgrade() -> None:
    op.drop_column("suppliers", "is_evaluation")
