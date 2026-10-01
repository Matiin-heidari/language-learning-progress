"""multi-user accounts

Revision ID: 2e274d140b5a
Revises: 58c992d33794
Create Date: 2026-10-01 16:53:32.778125

`language.code` and `activity_type.key` were globally UNIQUE (inline column
constraints, so SQLite gives them no discoverable name); autogenerate can't
emit a batch-mode drop for an unnamed constraint, so those two tables are
rebuilt by hand here instead of via batch_alter_table. `user_id` is added
nullable on existing rows -- run `flask claim-data` right after upgrading to
attach any pre-existing single-user data to a new account.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '2e274d140b5a'
down_revision = '58c992d33794'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'user',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('username', sa.String(length=32), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=True),
        sa.Column('password_hash', sa.String(length=255), nullable=False),
        sa.Column('display_name', sa.String(length=64), nullable=False),
        sa.Column('timezone', sa.String(length=64), nullable=False),
        sa.Column('week_start', sa.String(length=4), nullable=False),
        sa.Column('streak_min_minutes', sa.Integer(), nullable=False),
        sa.Column('daily_goal_minutes', sa.Integer(), nullable=False),
        sa.Column('theme', sa.String(length=8), nullable=False),
        sa.Column('is_public', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('email'),
    )
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_user_username'), ['username'], unique=True)

    op.drop_table('setting')

    # activity_type: drop the old global UNIQUE(key), add nullable user_id
    # (NULL = shared global default).
    op.execute(
        "CREATE TABLE activity_type_new ("
        "id INTEGER NOT NULL PRIMARY KEY, "
        "user_id INTEGER REFERENCES user(id), "
        "key VARCHAR(32) NOT NULL, "
        "name VARCHAR(64) NOT NULL, "
        "icon VARCHAR(32) NOT NULL, "
        "color_slot INTEGER NOT NULL, "
        "sort_order INTEGER NOT NULL, "
        "is_archived BOOLEAN NOT NULL"
        ")"
    )
    op.execute(
        "INSERT INTO activity_type_new "
        "(id, user_id, key, name, icon, color_slot, sort_order, is_archived) "
        "SELECT id, NULL, key, name, icon, color_slot, sort_order, is_archived FROM activity_type"
    )
    op.drop_table('activity_type')
    op.execute("ALTER TABLE activity_type_new RENAME TO activity_type")

    # language: drop the old global UNIQUE(code), add user_id (nullable for
    # now -- pre-existing rows are claimed by `flask claim-data`) with a new
    # UNIQUE(user_id, code) so every account can have its own "de".
    op.execute(
        "CREATE TABLE language_new ("
        "id INTEGER NOT NULL PRIMARY KEY, "
        "user_id INTEGER REFERENCES user(id), "
        "code VARCHAR(8) NOT NULL, "
        "name VARCHAR(64) NOT NULL, "
        "native_name VARCHAR(64) NOT NULL, "
        "flag_emoji VARCHAR(8) NOT NULL, "
        "accent_color VARCHAR(9), "
        "goal_level_id INTEGER REFERENCES level(id), "
        "is_active BOOLEAN NOT NULL, "
        "created_at DATETIME NOT NULL, "
        "CONSTRAINT uq_language_user_code UNIQUE (user_id, code)"
        ")"
    )
    op.execute(
        "INSERT INTO language_new "
        "(id, user_id, code, name, native_name, flag_emoji, accent_color, goal_level_id, "
        "is_active, created_at) "
        "SELECT id, NULL, code, name, native_name, flag_emoji, accent_color, goal_level_id, "
        "is_active, created_at FROM language"
    )
    op.drop_table('language')
    op.execute("ALTER TABLE language_new RENAME TO language")

    # study_session: plain nullable ADD COLUMN is fine here, no uniqueness change.
    with op.batch_alter_table('study_session', schema=None) as batch_op:
        batch_op.add_column(sa.Column('user_id', sa.Integer(), nullable=True))
        batch_op.create_index('ix_session_user_date', ['user_id', 'study_date'], unique=False)
        batch_op.create_foreign_key('fk_study_session_user', 'user', ['user_id'], ['id'])


def downgrade():
    with op.batch_alter_table('study_session', schema=None) as batch_op:
        batch_op.drop_constraint('fk_study_session_user', type_='foreignkey')
        batch_op.drop_index('ix_session_user_date')
        batch_op.drop_column('user_id')

    op.execute(
        "CREATE TABLE language_old ("
        "id INTEGER NOT NULL PRIMARY KEY, "
        "code VARCHAR(8) NOT NULL UNIQUE, "
        "name VARCHAR(64) NOT NULL, "
        "native_name VARCHAR(64) NOT NULL, "
        "flag_emoji VARCHAR(8) NOT NULL, "
        "accent_color VARCHAR(9), "
        "goal_level_id INTEGER REFERENCES level(id), "
        "is_active BOOLEAN NOT NULL, "
        "created_at DATETIME NOT NULL"
        ")"
    )
    op.execute(
        "INSERT INTO language_old "
        "(id, code, name, native_name, flag_emoji, accent_color, goal_level_id, is_active, created_at) "
        "SELECT id, code, name, native_name, flag_emoji, accent_color, goal_level_id, is_active, created_at "
        "FROM language"
    )
    op.drop_table('language')
    op.execute("ALTER TABLE language_old RENAME TO language")

    op.execute(
        "CREATE TABLE activity_type_old ("
        "id INTEGER NOT NULL PRIMARY KEY, "
        "key VARCHAR(32) NOT NULL UNIQUE, "
        "name VARCHAR(64) NOT NULL, "
        "icon VARCHAR(32) NOT NULL, "
        "color_slot INTEGER NOT NULL, "
        "sort_order INTEGER NOT NULL, "
        "is_archived BOOLEAN NOT NULL"
        ")"
    )
    op.execute(
        "INSERT INTO activity_type_old (id, key, name, icon, color_slot, sort_order, is_archived) "
        "SELECT id, key, name, icon, color_slot, sort_order, is_archived FROM activity_type"
    )
    op.drop_table('activity_type')
    op.execute("ALTER TABLE activity_type_old RENAME TO activity_type")

    op.create_table(
        'setting',
        sa.Column('key', sa.VARCHAR(length=64), nullable=False),
        sa.Column('value', sa.VARCHAR(length=255), nullable=False),
        sa.PrimaryKeyConstraint('key'),
    )
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_user_username'))

    op.drop_table('user')
