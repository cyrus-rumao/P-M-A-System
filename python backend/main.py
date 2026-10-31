from __future__ import annotations

import secrets
from datetime import datetime
from typing import Any

from authlib.integrations.starlette_client import OAuth
from bson import ObjectId
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from passlib.context import CryptContext
from pydantic import BaseModel, EmailStr, Field, field_validator
from pymongo import ReturnDocument
from starlette.middleware.sessions import SessionMiddleware

from config import get_settings
from db import db, lifespan, now

settings = get_settings()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
app = FastAPI(title="P-M-A-System API", lifespan=lifespan)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret or "development-only-session-secret",
    max_age=86400,
    same_site="lax",
    https_only=settings.node_env == "production",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

oauth = OAuth()
if settings.google_client_id and settings.google_client_secret:
    oauth.register(
        name="google",
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )

ROLES = {"OWNER", "ADMIN", "MEMBER"}
PERMISSIONS = {
    "OWNER": {
        "CREATE_WORKSPACE", "EDIT_WORKSPACE", "DELETE_WORKSPACE",
        "MANAGE_WORKSPACE_SETTINGS", "ADD_MEMBER", "CHANGE_MEMBER_ROLE",
        "REMOVE_MEMBER", "CREATE_PROJECT", "EDIT_PROJECT", "DELETE_PROJECT",
        "CREATE_TASK", "EDIT_TASK", "DELETE_TASK", "VIEW_ONLY",
    },
    "ADMIN": {
        "ADD_MEMBER", "CREATE_PROJECT", "EDIT_PROJECT", "DELETE_PROJECT",
        "CREATE_TASK", "EDIT_TASK", "DELETE_TASK",
        "MANAGE_WORKSPACE_SETTINGS", "VIEW_ONLY",
    },
    "MEMBER": {"VIEW_ONLY", "CREATE_TASK", "EDIT_TASK"},
}
TASK_STATUSES = {"BACKLOG", "TODO", "IN_PROGRESS", "IN_REVIEW", "DONE"}
TASK_PRIORITIES = {"LOW", "MEDIUM", "HIGH"}


class RegisterBody(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    email: EmailStr
    password: str = Field(min_length=4)

    @field_validator("name", "password", mode="before")
    @classmethod
    def trim(cls, value: str) -> str:
        return value.strip()


class LoginBody(BaseModel):
    email: EmailStr
    password: str = Field(min_length=4)


class WorkspaceBody(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None


class RoleBody(BaseModel):
    roleId: str = Field(min_length=1)
    memberId: str = Field(min_length=1)


class ProjectBody(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    emoji: str | None = None
    description: str | None = None


class TaskBody(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str | None = None
    priority: str
    status: str
    assignedTo: str | None = None
    dueDate: datetime | None = None

    @field_validator("priority")
    @classmethod
    def valid_priority(cls, value: str) -> str:
        if value not in TASK_PRIORITIES:
            raise ValueError("Invalid task priority")
        return value

    @field_validator("status")
    @classmethod
    def valid_status(cls, value: str) -> str:
        if value not in TASK_STATUSES:
            raise ValueError("Invalid task status")
        return value


def oid(value: str) -> ObjectId:
    if not ObjectId.is_valid(value):
        raise HTTPException(400, "Invalid ID")
    return ObjectId(value)


def clean(value: Any) -> Any:
    if isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, list):
        return [clean(item) for item in value]
    if isinstance(value, dict):
        return {key: clean(item) for key, item in value.items() if key != "password"}
    return value


def error(message: str, code: str, status_code: int) -> JSONResponse:
    return JSONResponse({"message": message, "errorCode": code}, status_code)


async def current_user(request: Request) -> dict[str, Any]:
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(401, "Unauthorized. Please log in.")
    user = await db().users.find_one({"_id": oid(user_id)})
    if not user:
        request.session.clear()
        raise HTTPException(401, "Unauthorized. Please log in.")
    return user


async def workspace_role(user_id: ObjectId, workspace_id: str) -> str:
    workspace = await db().workspaces.find_one({"_id": oid(workspace_id)})
    if not workspace:
        raise HTTPException(404, "Workspace not found")
    member = await db().members.find_one({"userId": user_id, "workspaceId": workspace["_id"]})
    if not member:
        raise HTTPException(401, "You are not a member of this workspace")
    role = await db().roles.find_one({"_id": member["role"]})
    if not role:
        raise HTTPException(404, "Role not found")
    return role["name"]


async def require_permission(user: dict[str, Any], workspace_id: str, permission: str) -> None:
    role = await workspace_role(user["_id"], workspace_id)
    if permission not in PERMISSIONS.get(role, set()):
        raise HTTPException(403, "You do not have permission to perform this action")


async def create_user_workspace(user_id: ObjectId, name: str) -> ObjectId:
    role = await db().roles.find_one({"name": "OWNER"})
    if not role:
        raise HTTPException(404, "Owner role not found")
    workspace_id = ObjectId()
    await db().workspaces.insert_one({
        "_id": workspace_id, "name": "My Workspace",
        "description": f"Workspace created for {name}", "owner": user_id,
        "inviteCode": secrets.token_hex(4), "createdAt": now(), "updatedAt": now(),
    })
    await db().members.insert_one({
        "userId": user_id, "workspaceId": workspace_id, "role": role["_id"],
        "joinedAt": now(), "createdAt": now(), "updatedAt": now(),
    })
    await db().users.update_one({"_id": user_id}, {"$set": {"currentWorkspace": workspace_id, "updatedAt": now()}})
    return workspace_id


@app.exception_handler(HTTPException)
async def http_error_handler(request: Request, exc: HTTPException):
    code = "ACCESS_UNAUTHORIZED" if exc.status_code == 401 else "RESOURCE_NOT_FOUND" if exc.status_code == 404 else "VALIDATION_ERROR"
    return error(str(exc.detail), code, exc.status_code)


@app.get("/")
async def root():
    return error("This is a bad request", "AUTH_INVALID_TOKEN", 400)


@app.post(f"{settings.base_path}/auth/register", status_code=201)
async def register(body: RegisterBody):
    email = str(body.email).lower()
    if await db().users.find_one({"email": email}):
        raise HTTPException(400, "Email already exists")
    user_id = ObjectId()
    await db().users.insert_one({
        "_id": user_id, "name": body.name.strip(), "email": email,
        "password": pwd_context.hash(body.password), "profilePicture": None,
        "isActive": True, "lastLogin": None, "currentWorkspace": None,
        "createdAt": now(), "updatedAt": now(),
    })
    await db().accounts.insert_one({"userId": user_id, "provider": "EMAIL", "providerId": email, "refreshToken": None, "tokenExpiry": None, "createdAt": now(), "updatedAt": now()})
    await create_user_workspace(user_id, body.name.strip())
    return {"message": "User created successfully"}


@app.post(f"{settings.base_path}/auth/login")
async def login(body: LoginBody, request: Request):
    account = await db().accounts.find_one({"provider": "EMAIL", "providerId": str(body.email).lower()})
    user = await db().users.find_one({"_id": account["userId"]}) if account else None
    if not user or not user.get("password") or not pwd_context.verify(body.password, user["password"]):
        return error("Invalid email or password", "ACCESS_UNAUTHORIZED", 401)
    request.session["user_id"] = str(user["_id"])
    return {"message": "Logged in successfully", "user": clean(user)}


@app.post(f"{settings.base_path}/auth/logout")
async def logout(request: Request):
    request.session.clear()
    return {"message": "Logged out successfully"}


@app.get(f"{settings.base_path}/auth/google")
async def google_login(request: Request):
    if not oauth.google:
        raise HTTPException(500, "Google OAuth is not configured")
    return await oauth.google.authorize_redirect(request, settings.google_callback_url)


@app.get(f"{settings.base_path}/auth/google/callback")
async def google_callback(request: Request):
    if not oauth.google:
        return RedirectResponse(f"{settings.frontend_google_callback_url}?status=failure")
    try:
        token = await oauth.google.authorize_access_token(request)
        profile = token.get("userinfo") or await oauth.google.parse_id_token(request, token)
        email = profile.get("email")
        google_id = profile.get("sub")
        if not email or not google_id:
            raise ValueError("Google profile is missing required fields")
        user = await db().users.find_one({"email": email})
        if not user:
            user_id = ObjectId()
            await db().users.insert_one({"_id": user_id, "email": email, "name": profile.get("name", ""), "profilePicture": profile.get("picture"), "isActive": True, "lastLogin": None, "currentWorkspace": None, "createdAt": now(), "updatedAt": now()})
            await db().accounts.insert_one({"userId": user_id, "provider": "GOOGLE", "providerId": google_id, "createdAt": now(), "updatedAt": now()})
            workspace_id = await create_user_workspace(user_id, profile.get("name", "User"))
            user = await db().users.find_one({"_id": user_id})
        else:
            workspace_id = user.get("currentWorkspace")
        request.session["user_id"] = str(user["_id"]) # type: ignore
        if not workspace_id:
            return RedirectResponse(f"{settings.frontend_google_callback_url}?status=failure")
        return RedirectResponse(f"{settings.frontend_origin}/workspace/{workspace_id}")
    except Exception:
        return RedirectResponse(f"{settings.frontend_google_callback_url}?status=failure")


@app.get(f"{settings.base_path}/user/current")
async def get_current_user(user: dict[str, Any] = Depends(current_user)):
    workspace = await db().workspaces.find_one({"_id": user.get("currentWorkspace")}) if user.get("currentWorkspace") else None
    result = clean(user)
    result["currentWorkspace"] = clean(workspace)
    return {"message": "User fetch successfully", "user": result}


@app.post(f"{settings.base_path}/workspace/create/new", status_code=201)
async def create_workspace(body: WorkspaceBody, user=Depends(current_user)):
    workspace_id = ObjectId()
    role = await db().roles.find_one({"name": "OWNER"})
    if not role:
        raise HTTPException(404, "Owner role not found")
    workspace = {"_id": workspace_id, "name": body.name.strip(), "description": body.description, "owner": user["_id"], "inviteCode": secrets.token_hex(4), "createdAt": now(), "updatedAt": now()}
    await db().workspaces.insert_one(workspace)
    await db().members.insert_one({"userId": user["_id"], "workspaceId": workspace_id, "role": role["_id"], "joinedAt": now(), "createdAt": now(), "updatedAt": now()})
    await db().users.update_one({"_id": user["_id"]}, {"$set": {"currentWorkspace": workspace_id, "updatedAt": now()}})
    return {"message": "Workspace created successfully", "workspace": clean(workspace)}


@app.get(f"{settings.base_path}/workspace/all")
async def all_workspaces(user=Depends(current_user)):
    memberships = await db().members.find({"userId": user["_id"]}).to_list(None)
    workspaces = await db().workspaces.find({"_id": {"$in": [m["workspaceId"] for m in memberships]}}).to_list(None)
    return {"message": "User workspaces fetched successfully", "workspaces": clean(workspaces)}


@app.get(f"{settings.base_path}/workspace/{{id}}")
async def get_workspace(id: str, user=Depends(current_user)):
    await workspace_role(user["_id"], id)
    workspace = await db().workspaces.find_one({"_id": oid(id)})
    members = await db().members.find({"workspaceId": oid(id)}).to_list(None)
    for member in members:
        member["role"] = await db().roles.find_one({"_id": member["role"]})
    workspace["members"] = members # type: ignore
    return {"message": "Workspace fetched successfully", "workspace": clean(workspace)}


@app.get(f"{settings.base_path}/workspace/members/{{id}}")
async def workspace_members(id: str, user=Depends(current_user)):
    await require_permission(user, id, "VIEW_ONLY")
    members = await db().members.find({"workspaceId": oid(id)}).to_list(None)
    roles = await db().roles.find({}, {"name": 1}).to_list(None)
    for member in members:
        member["userId"] = await db().users.find_one({"_id": member["userId"]}, {"password": 0})
        member["role"] = await db().roles.find_one({"_id": member["role"]}, {"name": 1})
    return {"message": "Workspace members retrieved successfully", "members": clean(members), "roles": clean(roles)}


@app.get(f"{settings.base_path}/workspace/analytics/{{id}}")
async def workspace_analytics(id: str, user=Depends(current_user)):
    await require_permission(user, id, "VIEW_ONLY")
    query = {"workspace": oid(id)}
    total = await db().tasks.count_documents(query)
    overdue = await db().tasks.count_documents({**query, "dueDate": {"$lt": now()}, "status": {"$ne": "DONE"}})
    completed = await db().tasks.count_documents({**query, "status": "DONE"})
    return {"message": "Workspace analytics retrieved successfully", "analytics": {"totalTasks": total, "overdueTasks": overdue, "completedTasks": completed}}


@app.put(f"{settings.base_path}/workspace/change/member/role/{{id}}")
async def change_member_role(id: str, body: RoleBody, user=Depends(current_user)):
    await require_permission(user, id, "CHANGE_MEMBER_ROLE")
    role = await db().roles.find_one({"_id": oid(body.roleId)})
    if not role:
        raise HTTPException(404, "Role not found")
    result = await db().members.find_one_and_update({"userId": oid(body.memberId), "workspaceId": oid(id)}, {"$set": {"role": role["_id"], "updatedAt": now()}}, return_document=ReturnDocument.AFTER)
    if not result:
        raise HTTPException(404, "Member not found in the workspace")
    return {"message": "Member Role changed successfully", "member": clean(result)}


@app.put(f"{settings.base_path}/workspace/update/{{id}}")
async def update_workspace(id: str, body: WorkspaceBody, user=Depends(current_user)):
    await require_permission(user, id, "EDIT_WORKSPACE")
    result = await db().workspaces.find_one_and_update({"_id": oid(id)}, {"$set": {"name": body.name, "description": body.description, "updatedAt": now()}}, return_document=ReturnDocument.AFTER)
    if not result:
        raise HTTPException(404, "Workspace not found")
    return {"message": "Workspace updated successfully", "workspace": clean(result)}


@app.delete(f"{settings.base_path}/workspace/delete/{{id}}")
async def delete_workspace(id: str, user=Depends(current_user)):
    await require_permission(user, id, "DELETE_WORKSPACE")
    workspace = await db().workspaces.find_one({"_id": oid(id)})
    if not workspace:
        raise HTTPException(404, "Workspace not found")
    if workspace["owner"] != user["_id"]:
        raise HTTPException(400, "You are not authorized to delete this workspace")
    await db().projects.delete_many({"workspace": workspace["_id"]})
    await db().tasks.delete_many({"workspace": workspace["_id"]})
    await db().members.delete_many({"workspaceId": workspace["_id"]})
    await db().workspaces.delete_one({"_id": workspace["_id"]})
    await db().users.update_one({"_id": user["_id"]}, {"$set": {"currentWorkspace": None, "updatedAt": now()}})
    return {"message": "Workspace deleted successfully", "currentWorkspace": None}


@app.post(f"{settings.base_path}/member/workspace/{{inviteCode}}/join")
async def join_workspace(inviteCode: str, user=Depends(current_user)):
    workspace = await db().workspaces.find_one({"inviteCode": inviteCode})
    if not workspace:
        raise HTTPException(404, "Invalid invite code or workspace not found")
    if await db().members.find_one({"userId": user["_id"], "workspaceId": workspace["_id"]}):
        raise HTTPException(400, "You are already a member of this workspace")
    role = await db().roles.find_one({"name": "MEMBER"})
    if not role:
        raise HTTPException(404, "Role not found")
    await db().members.insert_one({"userId": user["_id"], "workspaceId": workspace["_id"], "role": role["_id"], "joinedAt": now(), "createdAt": now(), "updatedAt": now()})
    return {"message": "Successfully joined the workspace", "workspaceId": str(workspace["_id"]), "role": role["name"]}


async def project_or_404(workspace_id: str, project_id: str) -> dict:
    project = await db().projects.find_one({"_id": oid(project_id), "workspace": oid(workspace_id)})
    if not project:
        raise HTTPException(404, "Project not found or does not belong to the specified workspace")
    return project


@app.post(f"{settings.base_path}/project/workspace/{{workspaceId}}/create", status_code=201)
async def create_project(workspaceId: str, body: ProjectBody, user=Depends(current_user)):
    await require_permission(user, workspaceId, "CREATE_PROJECT")
    project = {"_id": ObjectId(), "name": body.name, "emoji": body.emoji or "📊", "description": body.description, "workspace": oid(workspaceId), "createdBy": user["_id"], "createdAt": now(), "updatedAt": now()}
    await db().projects.insert_one(project)
    return {"message": "Project created successfully", "project": clean(project)}


@app.get(f"{settings.base_path}/project/workspace/{{workspaceId}}/all")
async def list_projects(workspaceId: str, pageSize: int = 10, pageNumber: int = 1, user=Depends(current_user)):
    await require_permission(user, workspaceId, "VIEW_ONLY")
    query = {"workspace": oid(workspaceId)}
    total = await db().projects.count_documents(query)
    skip = max(0, (pageNumber - 1) * pageSize)
    projects = await db().projects.find(query).sort("createdAt", -1).skip(skip).limit(pageSize).to_list(None)
    return {"message": "Project fetched successfully", "projects": clean(projects), "pagination": {"totalCount": total, "pageSize": pageSize, "pageNumber": pageNumber, "totalPages": (total + pageSize - 1) // pageSize if pageSize else 0, "skip": skip, "limit": pageSize}}


@app.get(f"{settings.base_path}/project/{{id}}/workspace/{{workspaceId}}")
async def get_project(id: str, workspaceId: str, user=Depends(current_user)):
    await require_permission(user, workspaceId, "VIEW_ONLY")
    return {"message": "Project fetched successfully", "project": clean(await project_or_404(workspaceId, id))}


@app.get(f"{settings.base_path}/project/{{id}}/workspace/{{workspaceId}}/analytics")
async def project_analytics(id: str, workspaceId: str, user=Depends(current_user)):
    await require_permission(user, workspaceId, "VIEW_ONLY")
    await project_or_404(workspaceId, id)
    query = {"project": oid(id)}
    total = await db().tasks.count_documents(query)
    overdue = await db().tasks.count_documents({**query, "dueDate": {"$lt": now()}, "status": {"$ne": "DONE"}})
    completed = await db().tasks.count_documents({**query, "status": "DONE"})
    return {"message": "Project analytics retrieved successfully", "analytics": {"totalTasks": total, "overdueTasks": overdue, "completedTasks": completed}}


@app.put(f"{settings.base_path}/project/{{id}}/workspace/{{workspaceId}}/update")
async def update_project(id: str, workspaceId: str, body: ProjectBody, user=Depends(current_user)):
    await require_permission(user, workspaceId, "EDIT_PROJECT")
    await project_or_404(workspaceId, id)
    updates = {key: value for key, value in body.model_dump().items() if value is not None}
    result = await db().projects.find_one_and_update({"_id": oid(id)}, {"$set": {**updates, "updatedAt": now()}}, return_document=ReturnDocument.AFTER)
    return {"message": "Project updated successfully", "project": clean(result)}


@app.delete(f"{settings.base_path}/project/{{id}}/workspace/{{workspaceId}}/delete")
async def delete_project(id: str, workspaceId: str, user=Depends(current_user)):
    await require_permission(user, workspaceId, "DELETE_PROJECT")
    await project_or_404(workspaceId, id)
    await db().projects.delete_one({"_id": oid(id)})
    await db().tasks.delete_many({"project": oid(id)})
    return {"message": "Project deleted successfully"}


async def task_or_404(workspace_id: str, project_id: str, task_id: str) -> dict:
    await project_or_404(workspace_id, project_id)
    task = await db().tasks.find_one({"_id": oid(task_id), "workspace": oid(workspace_id), "project": oid(project_id)})
    if not task:
        raise HTTPException(404, "Task not found or does not belong to this project")
    return task


@app.post(f"{settings.base_path}/task/project/{{projectId}}/workspace/{{workspaceId}}/create")
async def create_task(projectId: str, workspaceId: str, body: TaskBody, user=Depends(current_user)):
    await require_permission(user, workspaceId, "CREATE_TASK")
    await project_or_404(workspaceId, projectId)
    if body.assignedTo and not await db().members.find_one({"userId": oid(body.assignedTo), "workspaceId": oid(workspaceId)}):
        raise HTTPException(400, "Assigned user is not a member of this workspace.")
    task = {"_id": ObjectId(), "taskCode": f"task-{secrets.token_hex(2)}", **body.model_dump(), "project": oid(projectId), "workspace": oid(workspaceId), "createdBy": user["_id"], "createdAt": now(), "updatedAt": now()}
    if task["assignedTo"]:
        task["assignedTo"] = oid(task["assignedTo"])
    await db().tasks.insert_one(task)
    return {"message": "Task created successfully", "task": clean(task)}


@app.put(f"{settings.base_path}/task/{{id}}/project/{{projectId}}/workspace/{{workspaceId}}/update")
async def update_task(id: str, projectId: str, workspaceId: str, body: TaskBody, user=Depends(current_user)):
    await require_permission(user, workspaceId, "EDIT_TASK")
    await task_or_404(workspaceId, projectId, id)
    updates = body.model_dump()
    if updates["assignedTo"]:
        updates["assignedTo"] = oid(updates["assignedTo"])
    await db().tasks.update_one({"_id": oid(id)}, {"$set": {**updates, "updatedAt": now()}})
    return {"message": "Task updated successfully", "task": clean(await db().tasks.find_one({"_id": oid(id)}))}


@app.get(f"{settings.base_path}/task/workspace/{{workspaceId}}/all")
async def list_tasks(workspaceId: str, projectId: str | None = None, status: str | None = None, priority: str | None = None, assignedTo: str | None = None, keyword: str | None = None, dueDate: str | None = None, pageSize: int = 10, pageNumber: int = 1, user=Depends(current_user)):
    await require_permission(user, workspaceId, "VIEW_ONLY")
    query: dict[str, Any] = {"workspace": oid(workspaceId)}
    if projectId: query["project"] = oid(projectId)
    if status: query["status"] = {"$in": status.split(",")}
    if priority: query["priority"] = {"$in": priority.split(",")}
    if assignedTo: query["assignedTo"] = {"$in": [oid(value) for value in assignedTo.split(",")]}
    if keyword: query["title"] = {"$regex": keyword, "$options": "i"}
    if dueDate:
        query["dueDate"] = datetime.fromisoformat(dueDate.replace("Z", "+00:00"))
    total = await db().tasks.count_documents(query)
    skip = max(0, (pageNumber - 1) * pageSize)
    tasks = await db().tasks.find(query).sort("createdAt", -1).skip(skip).limit(pageSize).to_list(None)
    return {"message": "All tasks fetched successfully", "tasks": clean(tasks), "pagination": {"pageSize": pageSize, "pageNumber": pageNumber, "totalCount": total, "totalPages": (total + pageSize - 1) // pageSize if pageSize else 0, "skip": skip}}


@app.get(f"{settings.base_path}/task/{{id}}/project/{{projectId}}/workspace/{{workspaceId}}")
async def get_task(id: str, projectId: str, workspaceId: str, user=Depends(current_user)):
    await require_permission(user, workspaceId, "VIEW_ONLY")
    return {"message": "All tasks fetched successfully", "task": clean(await task_or_404(workspaceId, projectId, id))}


@app.delete(f"{settings.base_path}/task/{{id}}/workspace/{{workspaceId}}/delete")
async def delete_task(id: str, workspaceId: str, user=Depends(current_user)):
    await require_permission(user, workspaceId, "DELETE_TASK")
    result = await db().tasks.delete_one({"_id": oid(id), "workspace": oid(workspaceId)})
    if not result.deleted_count:
        raise HTTPException(404, "Task not found or does not belong to the specified workspace")
    return {"message": "Task deleted successfully"}


async def seed_roles() -> None:
    for name, permissions in PERMISSIONS.items():
        await db().roles.update_one({"name": name}, {"$set": {"name": name, "permissions": list(permissions), "updatedAt": now()}, "$setOnInsert": {"createdAt": now()}}, upsert=True)
