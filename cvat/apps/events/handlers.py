# Copyright (C) 2023 CVAT.ai Corporation
#
# SPDX-License-Identifier: MIT

from copy import deepcopy
from datetime import datetime, timezone

from rest_framework.renderers import JSONRenderer
from crum import get_current_user, get_current_request

from cvat.apps.engine.models import (
    Organization,
    Project,
    Task,
    Job,
    User,
    CloudStorage,
    Issue,
    Comment,
    Label,
)
from cvat.apps.engine.serializers import (
    ProjectReadSerializer,
    TaskReadSerializer,
    JobReadSerializer,
    BasicUserSerializer,
    CloudStorageReadSerializer,
    IssueReadSerializer,
    CommentReadSerializer,
    LabelSerializer,
)
from cvat.apps.engine.models import ShapeType
from cvat.apps.organizations.serializers import OrganizationReadSerializer
from cvat.apps.webhooks.signals import project_id, organization_id
from cvat.apps.engine.log import vlogger

from .event import event_scope, create_event


def task_id(instance):
    if isinstance(instance, Task):
        return instance.id

    try:
        tid = getattr(instance, "task_id", None)
        if tid is None:
            return instance.get_task_id()
        return tid
    except Exception:
        return None

def job_id(instance):
    if isinstance(instance, Job):
        return instance.id

    return None

def _get_current_user(instance):
    if isinstance(instance, User):
        return instance

    if isinstance(instance, Job):
        return instance.segment.task.owner

    return get_current_user()

def user_id(instance):
    current_user = _get_current_user(instance)
    return getattr(current_user, "id", None)

def user_name(instance):
    current_user = _get_current_user(instance)
    return getattr(current_user, "username", None)

def user_email(instance):
    current_user = _get_current_user(instance)
    return getattr(current_user, "email", None)

def organization_slug(instance):
    if isinstance(instance, Organization):
        return instance.slug

    try:
        org = getattr(instance, "organization", None)
        if org is None:
            return instance.get_organization_slug()
        return org.slug
    except Exception:
        return None

def _get_instance_diff(old_data, data):
    ingone_related_fields = (
        "labels",
    )
    diff = {}
    for prop, value in data.items():
        if prop in ingone_related_fields:
            continue
        old_value = old_data.get(prop)
        if old_value != value:
            diff[prop] = {
                "old_value": old_value,
                "new_value": value,
            }

    return diff

def _cleanup_fields(obj):
    fields=(
        "slug",
        "id",
        "name",
        "username",
        "display_name",
        "message",
        "organization",
        "project",
        "size",
        "task",
        "tasks",
        "job",
        "jobs",
        "comments",
        "url",
        "issues",
        "attributes",
    )
    subfields=(
        "url",
    )

    data = {}
    for k, v in obj.items():
        if k in fields:
            continue
        if isinstance(v, dict):
            data[k] = {kk: vv for kk, vv in v.items() if kk not in subfields}
        else:
            data[k] = v
    return data

def _get_object_name(instance):
    if isinstance(instance, Organization) or \
        isinstance(instance, Project) or \
        isinstance(instance, Task) or \
        isinstance(instance, Job) or \
        isinstance(instance, Label):
        return getattr(instance, "name", None)

    if isinstance(instance, User):
        return getattr(instance, "username", None)

    if isinstance(instance, CloudStorage):
        return getattr(instance, "display_name", None)

    if isinstance(instance, Comment):
        return getattr(instance, "message", None)

    return None

def _get_serializer(instance):
    context = {
        "request": get_current_request()
    }

    serializer = None
    if isinstance(instance, Organization):
        serializer = OrganizationReadSerializer(instance=instance, context=context)
    if isinstance(instance, Project):
        serializer = ProjectReadSerializer(instance=instance, context=context)
    if isinstance(instance, Task):
        serializer = TaskReadSerializer(instance=instance, context=context)
    if isinstance(instance, Job):
        serializer = JobReadSerializer(instance=instance, context=context)
    if isinstance(instance, User):
        serializer = BasicUserSerializer(instance=instance, context=context)
    if isinstance(instance, CloudStorage):
        serializer = CloudStorageReadSerializer(instance=instance, context=context)
    if isinstance(instance, Issue):
        serializer = IssueReadSerializer(instance=instance, context=context)
    if isinstance(instance, Comment):
        serializer = CommentReadSerializer(instance=instance, context=context)
    if isinstance(instance, Label):
        serializer = LabelSerializer(instance=instance, context=context)

    if serializer :
        serializer.fields.pop("url", None)
    return serializer

def handle_create(scope, instance, **kwargs):
    oid = organization_id(instance)
    oslug = organization_slug(instance)
    pid = project_id(instance)
    tid = task_id(instance)
    jid = job_id(instance)
    uid = user_id(instance)
    uname = user_name(instance)
    uemail = user_email(instance)

    serializer = _get_serializer(instance=instance)
    try:
        payload = serializer.data
    except Exception:
        payload = {}

    payload = _cleanup_fields(obj=payload)
    event = create_event(
        scope=scope,
        obj_id=getattr(instance, 'id', None),
        obj_name=_get_object_name(instance),
        source='server',
        org_id=oid,
        org_slug=oslug,
        project_id=pid,
        task_id=tid,
        job_id=jid,
        user_id=uid,
        user_name=uname,
        user_email=uemail,
        payload=payload,
    )
    message = JSONRenderer().render(event).decode('UTF-8')

    vlogger.info(message)

def handle_update(scope, instance, old_instance, **kwargs):
    oid = organization_id(instance)
    oslug = organization_slug(instance)
    pid = project_id(instance)
    tid = task_id(instance)
    jid = job_id(instance)
    uid = user_id(instance)
    uname = user_name(instance)
    uemail = user_email(instance)

    old_serializer = _get_serializer(instance=old_instance)
    serializer = _get_serializer(instance=instance)
    diff = _get_instance_diff(old_data=old_serializer.data, data=serializer.data)

    timestamp = str(datetime.now(timezone.utc).timestamp())
    for prop, change in diff.items():
        change = _cleanup_fields(change)
        event = create_event(
            scope=scope,
            timestamp=timestamp,
            obj_name=prop,
            obj_id=getattr(instance, f'{prop}_id', None),
            obj_val=str(change["new_value"]),
            source='server',
            org_id=oid,
            org_slug=oslug,
            project_id=pid,
            task_id=tid,
            job_id=jid,
            user_id=uid,
            user_name=uname,
            user_email=uemail,
            payload= {
                "old_value": change["old_value"],
            },
        )

        message = JSONRenderer().render(event).decode('UTF-8')
        vlogger.info(message)

def handle_delete(scope, instance, **kwargs):
    oid = organization_id(instance)
    oslug = organization_slug(instance)
    pid = project_id(instance)
    tid = task_id(instance)
    jid = job_id(instance)
    uid = user_id(instance)
    uname = user_name(instance)
    uemail = user_email(instance)

    event = create_event(
        scope=scope,
        obj_id=getattr(instance, 'id', None),
        obj_name=_get_object_name(instance),
        source='server',
        org_id=oid,
        org_slug=oslug,
        project_id=pid,
        task_id=tid,
        job_id=jid,
        user_id=uid,
        user_name=uname,
        user_email=uemail,
    )
    message = JSONRenderer().render(event).decode('UTF-8')

    vlogger.info(message)

def handle_annotations_patch(instance, annotations, action, **kwargs):
    _annotations = deepcopy(annotations)
    def filter_shape_data(shape):
        data = {
            "id": shape["id"],
            "frame": shape["frame"],
            "attributes": shape["attributes"],
        }

        label_id = shape.get("label_id", None)
        if label_id:
            data["label_id"] = label_id

        return data

    pid = project_id(instance)
    oid = organization_id(instance)
    tid = task_id(instance)
    jid = job_id(instance)
    uid = user_id(instance)

    tags = [filter_shape_data(tag) for tag in _annotations.get("tags", [])]
    if tags:
        event = create_event(
            scope=event_scope(action, "tags"),
            source='server',
            count=len(tags),
            org_id=oid,
            project_id=pid,
            task_id=tid,
            job_id=jid,
            user_id=uid,
            payload=tags,
        )
        message = JSONRenderer().render(event).decode('UTF-8')
        vlogger.info(message)

    shapes_by_type = {shape_type[0]: [] for shape_type in ShapeType.choices()}
    for shape in _annotations.get("shapes", []):
        shapes_by_type[shape["type"]].append(filter_shape_data(shape))

    scope = event_scope(action, "shapes")
    for shape_type, shapes in shapes_by_type.items():
        if shapes:
            event = create_event(
                scope=scope,
                obj_name=shape_type,
                source='server',
                count=len(shapes),
                org_id=oid,
                project_id=pid,
                task_id=tid,
                job_id=jid,
                user_id=uid,
                payload=shapes,
            )
            message = JSONRenderer().render(event).decode('UTF-8')
            vlogger.info(message)

    tracks_by_type = {shape_type[0]: [] for shape_type in ShapeType.choices()}
    for track in _annotations.get("tracks", []):
        track_shapes = track.pop("shapes")
        track = filter_shape_data(track)
        track["shapes"] = []
        for track_shape in track_shapes:
            track["shapes"].append(filter_shape_data(track_shape))
        tracks_by_type[track_shapes[0]["type"]].append(track)

    scope = event_scope(action, "tracks")
    for track_type, tracks in tracks_by_type.items():
        if tracks:
            event = create_event(
                scope=scope,
                obj_name=track_type,
                source='server',
                count=len(tracks),
                org_id=oid,
                project_id=pid,
                task_id=tid,
                job_id=jid,
                user_id=uid,
                payload=tracks,
            )
            message = JSONRenderer().render(event).decode('UTF-8')
            vlogger.info(message)
