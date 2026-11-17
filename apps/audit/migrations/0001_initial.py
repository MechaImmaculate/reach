import apps.core.ids
import django.db.models.deletion
import django.db.models.functions.datetime
import pgtrigger.compiler
import pgtrigger.migrations
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('facilities', '0001_initial'),
        ('mothers', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='AuditLog',
            fields=[
                ('id', models.UUIDField(default=apps.core.ids.uuid7, editable=False, primary_key=True, serialize=False)),
                ('recorded_at', models.DateTimeField(db_default=django.db.models.functions.datetime.Now(), editable=False)),
                ('action', models.CharField(choices=[('create', 'Create'), ('update', 'Update'), ('delete', 'Delete'), ('login', 'Login'), ('login_failed', 'Login Failed'), ('override', 'Override'), ('consent_change', 'Consent Change'), ('export', 'Export'), ('access_grant', 'Access Grant'), ('access_revoke', 'Access Revoke')], max_length=16)),
                ('object_type', models.CharField(max_length=80)),
                ('object_id', models.CharField(max_length=64)),
                ('changes', models.JSONField(blank=True, default=dict)),
                ('ip', models.GenericIPAddressField(blank=True, null=True)),
                ('user_agent', models.CharField(blank=True, max_length=300)),
                ('request_id', models.UUIDField(blank=True, null=True)),
                ('occurred_at', models.DateTimeField()),
                ('actor', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('facility', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='+', to='facilities.facility')),
                ('mother', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='+', to='mothers.mother')),
            ],
            options={
                'abstract': False,
            },
        ),
        migrations.CreateModel(
            name='DataExport',
            fields=[
                ('id', models.UUIDField(default=apps.core.ids.uuid7, editable=False, primary_key=True, serialize=False)),
                ('recorded_at', models.DateTimeField(db_default=django.db.models.functions.datetime.Now(), editable=False)),
                ('kind', models.CharField(max_length=60)),
                ('scope', models.JSONField(default=dict)),
                ('purpose', models.CharField(max_length=200)),
                ('row_count', models.PositiveIntegerField()),
                ('small_cell_suppressed', models.BooleanField(default=False)),
                ('includes_synthetic', models.BooleanField(default=False)),
                ('occurred_at', models.DateTimeField()),
                ('actor', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='+', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'abstract': False,
            },
        ),
        migrations.CreateModel(
            name='SecurityIncident',
            fields=[
                ('id', models.UUIDField(default=apps.core.ids.uuid7, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(db_default=django.db.models.functions.datetime.Now(), editable=False)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('severity', models.CharField(choices=[('low', 'Low'), ('medium', 'Medium'), ('high', 'High'), ('critical', 'Critical')], max_length=8)),
                ('status', models.CharField(choices=[('detected', 'Detected'), ('contained', 'Contained'), ('closed', 'Closed')], default='detected', max_length=10)),
                ('description', models.TextField()),
                ('detected_at', models.DateTimeField()),
                ('contained_at', models.DateTimeField(blank=True, null=True)),
                ('closed_at', models.DateTimeField(blank=True, null=True)),
                ('notified_odpc_at', models.DateTimeField(blank=True, null=True)),
                ('notes', models.TextField(blank=True)),
                ('reported_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='+', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'abstract': False,
            },
        ),
        migrations.CreateModel(
            name='AccessLog',
            fields=[
                ('id', models.UUIDField(default=apps.core.ids.uuid7, editable=False, primary_key=True, serialize=False)),
                ('recorded_at', models.DateTimeField(db_default=django.db.models.functions.datetime.Now(), editable=False)),
                ('resource', models.CharField(max_length=80)),
                ('purpose', models.CharField(choices=[('care', 'Care'), ('referral', 'Referral'), ('follow_up', 'Follow Up'), ('administration', 'Administration'), ('break_glass', 'Break Glass')], max_length=16)),
                ('occurred_at', models.DateTimeField()),
                ('actor', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('facility', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='+', to='facilities.facility')),
                ('mother', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='+', to='mothers.mother')),
            ],
            options={
                'abstract': False,
                'indexes': [models.Index(fields=['mother', '-occurred_at'], name='accesslog_mother_idx'), models.Index(fields=['actor', '-occurred_at'], name='accesslog_actor_idx')],
            },
        ),
        pgtrigger.migrations.AddTrigger(
            model_name='accesslog',
            trigger=pgtrigger.compiler.Trigger(name='append_only', sql=pgtrigger.compiler.UpsertTriggerSql(func="RAISE EXCEPTION 'pgtrigger: Cannot update or delete rows from % table', TG_TABLE_NAME;", hash='ec7964a4c459c69dd1110addb5a094052661bb74', operation='UPDATE OR DELETE', pgid='pgtrigger_append_only_d991f', table='audit_accesslog', when='BEFORE')),
        ),
        migrations.AddIndex(
            model_name='auditlog',
            index=models.Index(fields=['object_type', 'object_id', '-occurred_at'], name='audit_object_idx'),
        ),
        migrations.AddIndex(
            model_name='auditlog',
            index=models.Index(fields=['actor', '-occurred_at'], name='audit_actor_idx'),
        ),
        migrations.AddIndex(
            model_name='auditlog',
            index=models.Index(fields=['mother', '-occurred_at'], name='audit_mother_idx'),
        ),
        pgtrigger.migrations.AddTrigger(
            model_name='auditlog',
            trigger=pgtrigger.compiler.Trigger(name='append_only', sql=pgtrigger.compiler.UpsertTriggerSql(func="RAISE EXCEPTION 'pgtrigger: Cannot update or delete rows from % table', TG_TABLE_NAME;", hash='5d6ea98f2d06c3401a026f07d96e29ee1cc8e78b', operation='UPDATE OR DELETE', pgid='pgtrigger_append_only_e464f', table='audit_auditlog', when='BEFORE')),
        ),
        pgtrigger.migrations.AddTrigger(
            model_name='dataexport',
            trigger=pgtrigger.compiler.Trigger(name='append_only', sql=pgtrigger.compiler.UpsertTriggerSql(func="RAISE EXCEPTION 'pgtrigger: Cannot update or delete rows from % table', TG_TABLE_NAME;", hash='b7cc25258719890f25ccb0eda265881ae8bfbedb', operation='UPDATE OR DELETE', pgid='pgtrigger_append_only_2e449', table='audit_dataexport', when='BEFORE')),
        ),
    ]
