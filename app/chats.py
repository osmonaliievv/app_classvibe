from datetime import datetime
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import joinedload

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    status,
    WebSocket,
    WebSocketDisconnect,
    UploadFile,
    File,
    Form,  # Добавлено для FormData
)
from sqlalchemy.orm import Session
from sqlalchemy import func, or_
import os
import json  # Добавлено для парсинга
from uuid import uuid4

from .database import get_db
from .auth import get_current_user
from . import models, schemas
from .notifications import create_notification
from .models import NotificationTypeEnum, MediaTypeEnum, MessageTypeEnum, ChatTypeEnum
from .utils import decode_access_token

router = APIRouter(prefix="/chats", tags=["chats"])

MEDIA_ROOT = "media"
CHATS_SUBDIR = "chats"
os.makedirs(os.path.join(MEDIA_ROOT, CHATS_SUBDIR), exist_ok=True)


# ---------- Вспомогательные функции ----------


async def _save_avatar(file: UploadFile, chat_id: int) -> str:
    """Вспомогательная функция для сохранения файла аватарки"""
    if not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Можно загружать только изображения")

    ext = os.path.splitext(file.filename)[1] or ".png"
    # Добавляем uuid для уникальности имени файла
    filename = f"chat_avatar_{chat_id}_{uuid4().hex[:8]}{ext}"
    save_dir = os.path.join(MEDIA_ROOT, "chat_avatars")
    os.makedirs(save_dir, exist_ok=True)
    save_path = os.path.join(save_dir, filename)

    with open(save_path, "wb") as f:
        content = await file.read()
        f.write(content)

    return f"/media/chat_avatars/{filename}"


def _parse_participant_ids(ids_data: Any) -> set:
    """Парсит participant_ids, которые могут прийти как список полей, JSON строка или байты"""
    if not ids_data:
        return set()

    # Если данные пришли в бинарном виде (иногда случается в формах)
    if isinstance(ids_data, bytes):
        ids_data = ids_data.decode()

    if isinstance(ids_data, str):
        try:
            parsed = json.loads(ids_data)
            if isinstance(parsed, list):
                return set(int(i) for i in parsed)
            return {int(parsed)}
        except:
            # Если прислали просто строку через запятую "1,2,3"
            return set(int(i) for i in ids_data.split(",") if i.strip())

    # Если данные уже пришли списком от FastAPI
    if isinstance(ids_data, list):
        return set(int(i) for i in ids_data)

    try:
        return {int(ids_data)}
    except:
        return set()


def get_or_create_direct_chat(
        db: Session,
        user_a_id: int,
        user_b_id: int,
) -> models.Chat:
    if user_a_id == user_b_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Нельзя создать чат с самим собой",
        )

    subq = (
        db.query(models.ChatParticipant.chat_id)
        .filter(models.ChatParticipant.user_id.in_([user_a_id, user_b_id]))
        .group_by(models.ChatParticipant.chat_id)
        .having(func.count(models.ChatParticipant.id) == 2)
        .subquery()
    )

    chat = (
        db.query(models.Chat)
        .filter(
            models.Chat.id.in_(subq),
            models.Chat.type == models.ChatTypeEnum.private,
            models.Chat.is_deleted == False,
        )
        .first()
    )

    if chat:
        return chat

    now = datetime.utcnow()
    chat = models.Chat(
        type=models.ChatTypeEnum.private,
        created_by_id=user_a_id,
        updated_at=now,
        created_at=now,
    )
    db.add(chat)
    db.flush()

    p1 = models.ChatParticipant(chat_id=chat.id, user_id=user_a_id)
    p2 = models.ChatParticipant(chat_id=chat.id, user_id=user_b_id)
    db.add(p1)
    db.add(p2)

    db.commit()
    db.refresh(chat)
    return chat


def _create_message_and_notify(
        db: Session,
        chat: models.Chat,
        sender: models.User,
        payload: schemas.MessageCreate,
) -> models.Message:
    if payload.type == MessageTypeEnum.text:
        if not payload.content:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Текст сообщения обязателен",
            )
    elif payload.type == MessageTypeEnum.media:
        if not payload.media_url or not payload.media_type:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Для медиа-сообщения нужны media_url и media_type",
            )
    elif payload.type == MessageTypeEnum.post_share:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Этот тип сообщения нельзя отправить напрямую",
        )
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Неподдерживаемый тип сообщения",
        )

    now = datetime.utcnow()
    msg = models.Message(
        chat_id=chat.id,
        sender_id=sender.id,
        type=payload.type,
        content=payload.content,
        media_url=payload.media_url,
        media_type=payload.media_type,
        created_at=now,
    )
    db.add(msg)
    db.flush()

    participants = (
        db.query(models.ChatParticipant)
        .filter(models.ChatParticipant.chat_id == chat.id)
        .all()
    )

    for p in participants:
        if p.user_id == sender.id:
            continue
        status_row = models.MessageStatus(
            message_id=msg.id,
            user_id=p.user_id,
            is_delivered=True,
            delivered_at=now,
        )
        db.add(status_row)

    chat.updated_at = now
    db.add(chat)
    db.commit()
    db.refresh(msg)

    for p in participants:
        if p.user_id == sender.id:
            continue
        create_notification(
            db=db,
            user_id=p.user_id,
            type=NotificationTypeEnum.new_message,
            title="Новое сообщение",
            body=f"{sender.first_name} {sender.last_name} (@{sender.username}) отправил сообщение",
            data={"chat_id": chat.id, "message_id": msg.id, "from_user_id": sender.id},
        )

    return msg


def _serialize_message(msg: models.Message, current_user_id: int | None = None) -> Dict[str, Any]:
    base = schemas.MessageOut.from_orm(msg)
    data = base.model_dump()

    if msg.sender:
        data["sender"] = {
            "id": msg.sender.id,
            "username": msg.sender.username,
            "first_name": msg.sender.first_name,
            "last_name": msg.sender.last_name,
            "avatar_url": msg.sender.avatar_url
        }

    read_count = sum(1 for s in msg.statuses if s.is_read)
    is_read_by_me = (
        any(s.user_id == current_user_id and s.is_read for s in msg.statuses)
        if current_user_id is not None
        else False
    )

    data["read_count"] = read_count
    data["is_read_by_me"] = is_read_by_me

    # ✅ Добавь reactions
    data["reactions"] = [
        {"emoji": r.emoji, "user_id": r.user_id}
        for r in msg.reactions
    ] if msg.reactions else []

    return data


def _ensure_chat_admin(db: Session, chat: models.Chat, user_id: int):
    if chat.type == ChatTypeEnum.private:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Операция недоступна для приватных чатов",
        )

    participant = (
        db.query(models.ChatParticipant)
        .filter(
            models.ChatParticipant.chat_id == chat.id,
            models.ChatParticipant.user_id == user_id,
        )
        .first()
    )
    if not participant or not participant.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Нужны права администратора чата",
        )


# ---------- WebSocket manager ----------


class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[int, List[Dict[str, Any]]] = {}

    async def connect(self, chat_id: int, user_id: int, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.setdefault(chat_id, []).append(
            {"ws": websocket, "user_id": user_id}
        )

    def disconnect(self, chat_id: int, websocket: WebSocket):
        if chat_id in self.active_connections:
            self.active_connections[chat_id] = [
                item
                for item in self.active_connections[chat_id]
                if item["ws"] is not websocket
            ]
            if not self.active_connections[chat_id]:
                self.active_connections.pop(chat_id, None)

    async def broadcast(self, chat_id: int, message: Dict[str, Any]):
        for item in self.active_connections.get(chat_id, []):
            await item["ws"].send_json(message)


manager = ConnectionManager()


# ---------- HTTP API ----------


@router.get("/", response_model=List[schemas.ChatOut])
def list_my_chats(chat_type: models.ChatTypeEnum | None = None, search: str | None = None,
                  db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    q = db.query(models.Chat).join(models.ChatParticipant).filter(models.ChatParticipant.user_id == current_user.id,
                                                                  models.Chat.is_deleted == False)

    if chat_type:
        q = q.filter(models.Chat.type == chat_type)

    chats = q.order_by(models.Chat.updated_at.desc()).all()

    result: List[schemas.ChatOut] = []
    for chat in chats:
        title = chat.title
        avatar_url = chat.avatar_url

        if chat.type == models.ChatTypeEnum.private:
            other_part = db.query(models.ChatParticipant).join(models.User).filter(
                models.ChatParticipant.chat_id == chat.id,
                models.ChatParticipant.user_id != current_user.id
            ).first()
            if other_part and other_part.user:
                title = f"{other_part.user.first_name} {other_part.user.last_name}"
                avatar_url = other_part.user.avatar_url

        last_msg = (
            db.query(models.Message)
            .filter(
                models.Message.chat_id == chat.id,
                models.Message.is_deleted == False,
            )
            .order_by(models.Message.created_at.desc())
            .first()
        )
        preview = None
        last_at = None
        if last_msg:
            if last_msg.type == models.MessageTypeEnum.text:
                preview = last_msg.content
            elif last_msg.type == models.MessageTypeEnum.media:
                preview = "Медиа"
            elif last_msg.type == models.MessageTypeEnum.post_share:
                preview = "Поделился постом"
            last_at = last_msg.created_at

        item = schemas.ChatOut(
            id=chat.id,
            type=chat.type,
            title=title,
            avatar_url=avatar_url,
            last_message_preview=preview,
            last_message_at=last_at,
        )
        result.append(item)

    return result


@router.get("/{chat_id}/messages", response_model=List[schemas.MessageOut])
def list_messages(
        chat_id: int,
        db: Session = Depends(get_db),
        current_user=Depends(get_current_user),
):
    participant = (
        db.query(models.ChatParticipant)
        .filter(
            models.ChatParticipant.chat_id == chat_id,
            models.ChatParticipant.user_id == current_user.id,
        )
        .first()
    )
    if not participant:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Нет доступа к чату",
        )

    messages = (
        db.query(models.Message)
        .options(joinedload(models.Message.sender))
        .outerjoin(
            models.MessageStatus,
            (models.MessageStatus.message_id == models.Message.id)
            & (models.MessageStatus.user_id == current_user.id),
        )
        .filter(
            models.Message.chat_id == chat_id,
            models.Message.is_deleted == False,
            or_(
                models.MessageStatus.id == None,
                models.MessageStatus.is_hidden == False,
            ),
        )
        .order_by(models.Message.created_at.asc())
        .all()
    )

    result: List[schemas.MessageOut] = []
    for msg in messages:
        serialized = _serialize_message(msg, current_user_id=current_user.id)
        result.append(schemas.MessageOut(**serialized))

    return result


@router.post(
    "/{chat_id}/messages",
    response_model=schemas.MessageOut,
    status_code=status.HTTP_201_CREATED,
)
def send_message(
        chat_id: int,
        payload: schemas.MessageCreate,
        db: Session = Depends(get_db),
        current_user=Depends(get_current_user),
):
    participant = (
        db.query(models.ChatParticipant)
        .filter(
            models.ChatParticipant.chat_id == chat_id,
            models.ChatParticipant.user_id == current_user.id,
        )
        .first()
    )
    if not participant:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Нет доступа к чату",
        )

    chat = (
        db.query(models.Chat)
        .filter(models.Chat.id == chat_id, models.Chat.is_deleted == False)
        .first()
    )
    if not chat:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Чат не найден",
        )

    if chat.type == models.ChatTypeEnum.channel and not participant.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Только админы канала могут отправлять сообщения",
        )

    msg = _create_message_and_notify(db, chat, current_user, payload)
    return schemas.MessageOut(**_serialize_message(msg, current_user_id=current_user.id))


@router.post("/{chat_id}/messages/read", response_model=schemas.SimpleMessage)
def mark_messages_read(
        chat_id: int,
        payload: schemas.MessageReadRequest,
        db: Session = Depends(get_db),
        current_user=Depends(get_current_user),
):
    participant = (
        db.query(models.ChatParticipant)
        .filter(
            models.ChatParticipant.chat_id == chat_id,
            models.ChatParticipant.user_id == current_user.id,
        )
        .first()
    )
    if not participant:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Нет доступа к чату",
        )

    now = datetime.utcnow()

    q = (
        db.query(models.MessageStatus)
        .join(models.Message)
        .filter(
            models.Message.chat_id == chat_id,
            models.MessageStatus.user_id == current_user.id,
        )
    )

    if payload.message_ids:
        q = q.filter(models.MessageStatus.message_id.in_(payload.message_ids))
    elif payload.up_to_message_id:
        q = q.filter(models.MessageStatus.message_id <= payload.up_to_message_id)
    else:
        raise HTTPException(
            status_code=400,
            detail="Нужно передать message_ids или up_to_message_id",
        )

    statuses = q.all()
    for s in statuses:
        s.is_read = True
        s.read_at = now
        db.add(s)

    db.commit()

    return schemas.SimpleMessage(message="Сообщения отмечены как прочитанные")


@router.patch("/{chat_id}/messages/{message_id}", response_model=schemas.MessageOut)
def edit_message(
        chat_id: int,
        message_id: int,
        payload: schemas.MessageEditRequest,
        db: Session = Depends(get_db),
        current_user=Depends(get_current_user),
):
    msg = (
        db.query(models.Message)
        .filter(
            models.Message.id == message_id,
            models.Message.chat_id == chat_id,
            models.Message.is_deleted == False,
        )
        .first()
    )
    if not msg:
        raise HTTPException(status_code=404, detail="Сообщение не найдено")

    if msg.sender_id != current_user.id:
        raise HTTPException(
            status_code=403,
            detail="Можно редактировать только свои сообщения",
        )

    msg.content = payload.content
    msg.is_edited = True
    msg.edited_at = datetime.utcnow()
    db.add(msg)
    db.commit()
    db.refresh(msg)

    serialized = _serialize_message(msg, current_user_id=current_user.id)
    return schemas.MessageOut(**serialized)


@router.delete("/{chat_id}/messages/{message_id}", response_model=schemas.SimpleMessage)
def delete_message(
        chat_id: int,
        message_id: int,
        payload: schemas.MessageDeleteRequest,
        db: Session = Depends(get_db),
        current_user=Depends(get_current_user),
):
    msg = (
        db.query(models.Message)
        .filter(
            models.Message.id == message_id,
            models.Message.chat_id == chat_id,
        )
        .first()
    )
    if not msg:
        raise HTTPException(status_code=404, detail="Сообщение не найдено")

    chat = db.query(models.Chat).filter(models.Chat.id == chat_id).first()
    if not chat:
        raise HTTPException(status_code=404, detail="Чат не найден")

    participant = (
        db.query(models.ChatParticipant)
        .filter(
            models.ChatParticipant.chat_id == chat_id,
            models.ChatParticipant.user_id == current_user.id,
        )
        .first()
    )
    if not participant:
        raise HTTPException(status_code=403, detail="Нет доступа к чату")

    if payload.delete_forall:
        is_admin = False
        if chat.type != ChatTypeEnum.private:
            admin_part = (
                db.query(models.ChatParticipant)
                .filter(
                    models.ChatParticipant.chat_id == chat_id,
                    models.ChatParticipant.user_id == current_user.id,
                    models.ChatParticipant.is_admin == True,
                )
                .first()
            )
            is_admin = admin_part is not None

        if msg.sender_id != current_user.id and not is_admin:
            raise HTTPException(
                status_code=403,
                detail="Удалить сообщение для всех может только автор или админ",
            )

        msg.is_deleted = True
        db.add(msg)
    else:
        status_row = (
            db.query(models.MessageStatus)
            .filter(
                models.MessageStatus.message_id == msg.id,
                models.MessageStatus.user_id == current_user.id,
            )
            .first()
        )
        now = datetime.utcnow()
        if not status_row:
            status_row = models.MessageStatus(
                message_id=msg.id,
                user_id=current_user.id,
                is_hidden=True,
                hidden_at=now,
            )
        else:
            status_row.is_hidden = True
            status_row.hidden_at = now
        db.add(status_row)

    db.commit()
    return schemas.SimpleMessage(message="Сообщение удалено")


@router.post("/{chat_id}/messages/{message_id}/reaction", response_model=schemas.SimpleMessage)
def set_reaction(
        chat_id: int,
        message_id: int,
        payload: schemas.ReactionRequest,
        db: Session = Depends(get_db),
        current_user=Depends(get_current_user),
):
    msg = (
        db.query(models.Message)
        .filter(
            models.Message.id == message_id,
            models.Message.chat_id == chat_id,
            models.Message.is_deleted == False,
        )
        .first()
    )
    if not msg:
        raise HTTPException(status_code=404, detail="Сообщение не найдено")

    existing = (
        db.query(models.MessageReaction)
        .filter(
            models.MessageReaction.message_id == message_id,
            models.MessageReaction.user_id == current_user.id,
        )
        .first()
    )

    if not payload.emoji:
        if existing:
            db.delete(existing)
            db.commit()
        return schemas.SimpleMessage(message="Реакция удалена")

    if existing:
        existing.emoji = payload.emoji
        db.add(existing)
    else:
        r = models.MessageReaction(
            message_id=message_id,
            user_id=current_user.id,
            emoji=payload.emoji,
        )
        db.add(r)

    db.commit()
    return schemas.SimpleMessage(message="Реакция обновлена")


@router.post(
    "/{chat_id}/messages/{message_id}/favorite",
    response_model=schemas.FavoriteToggleResponse,
)
def toggle_favorite(
        chat_id: int,
        message_id: int,
        db: Session = Depends(get_db),
        current_user=Depends(get_current_user),
):
    msg = (
        db.query(models.Message)
        .filter(
            models.Message.id == message_id,
            models.Message.chat_id == chat_id,
            models.Message.is_deleted == False,
        )
        .first()
    )
    if not msg:
        raise HTTPException(status_code=404, detail="Сообщение не найдено")

    existing = (
        db.query(models.FavoriteMessage)
        .filter(
            models.FavoriteMessage.message_id == message_id,
            models.FavoriteMessage.user_id == current_user.id,
        )
        .first()
    )

    if existing:
        db.delete(existing)
        db.commit()
        return schemas.FavoriteToggleResponse(is_favorite=False)

    fav = models.FavoriteMessage(
        message_id=message_id,
        user_id=current_user.id,
    )
    db.add(fav)
    db.commit()
    return schemas.FavoriteToggleResponse(is_favorite=True)


@router.get("/{chat_id}/favorites", response_model=List[schemas.MessageOut])
def list_favorites_in_chat(
        chat_id: int,
        db: Session = Depends(get_db),
        current_user=Depends(get_current_user),
):
    participant = (
        db.query(models.ChatParticipant)
        .filter(
            models.ChatParticipant.chat_id == chat_id,
            models.ChatParticipant.user_id == current_user.id,
        )
        .first()
    )
    if not participant:
        raise HTTPException(status_code=403, detail="Нет доступа к чату")

    favs = (
        db.query(models.FavoriteMessage)
        .join(models.Message, models.Message.id == models.FavoriteMessage.message_id)
        .filter(
            models.FavoriteMessage.user_id == current_user.id,
            models.Message.chat_id == chat_id,
            models.Message.is_deleted == False,
        )
        .order_by(models.FavoriteMessage.created_at.desc())
        .all()
    )

    messages = [f.message for f in favs]
    result: List[schemas.MessageOut] = []
    for msg in messages:
        serialized = _serialize_message(msg, current_user_id=current_user.id)
        result.append(schemas.MessageOut(**serialized))
    return result


@router.post("/{chat_id}/pin/{message_id}", response_model=schemas.ChatOut)
def pin_message(
        chat_id: int,
        message_id: int,
        db: Session = Depends(get_db),
        current_user=Depends(get_current_user),
):
    chat = (
        db.query(models.Chat)
        .filter(models.Chat.id == chat_id, models.Chat.is_deleted == False)
        .first()
    )
    if not chat:
        raise HTTPException(status_code=404, detail="Чат не найден")

    _ensure_chat_admin(db, chat, current_user.id)

    msg = (
        db.query(models.Message)
        .filter(
            models.Message.id == message_id,
            models.Message.chat_id == chat_id,
            models.Message.is_deleted == False,
        )
        .first()
    )
    if not msg:
        raise HTTPException(status_code=404, detail="Сообщение не найдено")

    (
        db.query(models.PinnedMessage)
        .filter(
            models.PinnedMessage.chat_id == chat_id,
            models.PinnedMessage.is_active == True,
        )
        .update({"is_active": False})
    )

    pin = models.PinnedMessage(
        chat_id=chat_id,
        message_id=message_id,
        pinned_by_id=current_user.id,
        is_active=True,
    )
    db.add(pin)
    db.commit()
    db.refresh(chat)

    return schemas.ChatOut(
        id=chat.id,
        type=chat.type,
        title=chat.title,
        avatar_url=chat.avatar_url,
        last_message_preview=None,
        last_message_at=chat.updated_at,
    )


@router.post("/{chat_id}/unpin", response_model=schemas.ChatOut)
def unpin_message(
        chat_id: int,
        db: Session = Depends(get_db),
        current_user=Depends(get_current_user),
):
    chat = (
        db.query(models.Chat)
        .filter(models.Chat.id == chat_id, models.Chat.is_deleted == False)
        .first()
    )
    if not chat:
        raise HTTPException(status_code=404, detail="Чат не найден")

    _ensure_chat_admin(db, chat, current_user.id)

    (
        db.query(models.PinnedMessage)
        .filter(
            models.PinnedMessage.chat_id == chat_id,
            models.PinnedMessage.is_active == True,
        )
        .update({"is_active": False})
    )
    db.commit()
    db.refresh(chat)

    return schemas.ChatOut(
        id=chat.id,
        type=chat.type,
        title=chat.title,
        avatar_url=chat.avatar_url,
        last_message_preview=None,
        last_message_at=chat.updated_at,
    )


@router.post("/direct/{user_id}", response_model=schemas.ChatOut)
def open_direct_chat(
        user_id: int,
        db: Session = Depends(get_db),
        current_user=Depends(get_current_user),
):
    chat = get_or_create_direct_chat(db, current_user.id, user_id)

    last_msg = (
        db.query(models.Message)
        .filter(
            models.Message.chat_id == chat.id,
            models.Message.is_deleted == False,
        )
        .order_by(models.Message.created_at.desc())
        .first()
    )
    preview = None
    last_at = None
    if last_msg:
        if last_msg.type == MessageTypeEnum.text:
            preview = last_msg.content
        elif last_msg.type == MessageTypeEnum.media:
            preview = "Медиа"
        elif last_msg.type == MessageTypeEnum.post_share:
            preview = "Поделился постом"
        last_at = last_msg.created_at

    return schemas.ChatOut(
        id=chat.id,
        type=chat.type,
        title=chat.title,
        avatar_url=chat.avatar_url,
        last_message_preview=preview,
        last_message_at=last_at,
    )


@router.post("/group", response_model=schemas.ChatOut, status_code=status.HTTP_201_CREATED)
async def create_group_chat(
        title: str = Form(...),
        participant_ids: str = Form(...),
        avatar_url: Optional[UploadFile] = File(None),
        db: Session = Depends(get_db),
        current_user=Depends(get_current_user),
):
    """СОЗДАНИЕ ГРУППЫ С АВАТАРКОЙ ОДНИМ ЗАПРОСОМ"""
    now = datetime.utcnow()
    chat = models.Chat(
        type=models.ChatTypeEnum.group,
        title=title,
        created_by_id=current_user.id,
        created_at=now,
        updated_at=now,
    )
    db.add(chat)
    db.flush()  # Получаем chat.id

    # ✅ Сохраняем фото, если оно пришло в запросе
    if avatar_url:
        chat.avatar_url = await _save_avatar(avatar_url, chat.id)

    creator_part = models.ChatParticipant(
        chat_id=chat.id,
        user_id=current_user.id,
        is_admin=True,
    )
    db.add(creator_part)

    ids = _parse_participant_ids(participant_ids)
    unique_ids = set(pid for pid in ids if pid != current_user.id)
    if unique_ids:
        users = (
            db.query(models.User)
            .filter(models.User.id.in_(unique_ids), models.User.is_active == True)
            .all()
        )
        for u in users:
            db.add(models.ChatParticipant(chat_id=chat.id, user_id=u.id, is_admin=False))

    db.commit()
    db.refresh(chat)

    return chat


@router.post("/channel", response_model=schemas.ChatOut, status_code=status.HTTP_201_CREATED)
async def create_channel(
        title: str = Form(...),
        participant_ids: str = Form(...),
        avatar_url: Optional[UploadFile] = File(None),
        db: Session = Depends(get_db),
        current_user=Depends(get_current_user),
):
    """СОЗДАНИЕ КАНАЛА С АВАТАРКОЙ ОДНИМ ЗАПРОСОМ"""
    now = datetime.utcnow()
    chat = models.Chat(
        type=models.ChatTypeEnum.channel,
        title=title,
        created_by_id=current_user.id,
        created_at=now,
        updated_at=now,
    )
    db.add(chat)
    db.flush()

    if avatar_url:
        chat.avatar_url = await _save_avatar(avatar_url, chat.id)

    creator_part = models.ChatParticipant(
        chat_id=chat.id,
        user_id=current_user.id,
        is_admin=True,
    )
    db.add(creator_part)

    ids = _parse_participant_ids(participant_ids)
    unique_ids = set(pid for pid in ids if pid != current_user.id)
    if unique_ids:
        users = (
            db.query(models.User)
            .filter(models.User.id.in_(unique_ids), models.User.is_active == True)
            .all()
        )
        for u in users:
            db.add(models.ChatParticipant(chat_id=chat.id, user_id=u.id, is_admin=False))

    db.commit()
    db.refresh(chat)

    return chat


# ------- Админ-панель групп/каналов -------


@router.post("/{chat_id}/set-admin/{user_id}", response_model=schemas.SimpleMessage)
def set_chat_admin(
        chat_id: int,
        user_id: int,
        db: Session = Depends(get_db),
        current_user=Depends(get_current_user),
):
    chat = (
        db.query(models.Chat)
        .filter(models.Chat.id == chat_id, models.Chat.is_deleted == False)
        .first()
    )
    if not chat:
        raise HTTPException(status_code=404, detail="Чат не найден")

    _ensure_chat_admin(db, chat, current_user.id)

    participant = (
        db.query(models.ChatParticipant)
        .filter(
            models.ChatParticipant.chat_id == chat_id,
            models.ChatParticipant.user_id == user_id,
        )
        .first()
    )
    if not participant:
        raise HTTPException(status_code=404, detail="Пользователь не найден в чате")

    participant.is_admin = True
    db.add(participant)
    db.commit()
    return schemas.SimpleMessage(message="Пользователь назначен админом")


@router.post("/{chat_id}/ban/{user_id}", response_model=schemas.SimpleMessage)
def ban_user(
        chat_id: int,
        user_id: int,
        db: Session = Depends(get_db),
        current_user=Depends(get_current_user),
):
    chat = (
        db.query(models.Chat)
        .filter(models.Chat.id == chat_id, models.Chat.is_deleted == False)
        .first()
    )
    if not chat:
        raise HTTPException(status_code=404, detail="Чат не найден")

    _ensure_chat_admin(db, chat, current_user.id)

    if current_user.id == user_id:
        raise HTTPException(status_code=400, detail="Нельзя забанить самого себя")

    (
        db.query(models.ChatParticipant)
        .filter(
            models.ChatParticipant.chat_id == chat_id,
            models.ChatParticipant.user_id == user_id,
        )
        .delete()
    )

    db.commit()
    return schemas.SimpleMessage(message="Пользователь забанен в чате")


@router.post("/{chat_id}/rename", response_model=schemas.ChatOut)
def rename_chat(
        chat_id: int,
        new_title: str,
        db: Session = Depends(get_db),
        current_user=Depends(get_current_user),
):
    chat = (
        db.query(models.Chat)
        .filter(models.Chat.id == chat_id, models.Chat.is_deleted == False)
        .first()
    )
    if not chat:
        raise HTTPException(status_code=404, detail="Чат не найден")

    _ensure_chat_admin(db, chat, current_user.id)

    chat.title = new_title
    chat.updated_at = datetime.utcnow()
    db.add(chat)
    db.commit()
    db.refresh(chat)

    return schemas.ChatOut(
        id=chat.id,
        type=chat.type,
        title=chat.title,
        avatar_url=chat.avatar_url,
        last_message_preview=None,
        last_message_at=chat.updated_at,
    )


@router.post("/{chat_id}/avatar", response_model=schemas.ChatOut)
async def upload_chat_avatar(
        chat_id: int,
        file: UploadFile = File(...),
        db: Session = Depends(get_db),
        current_user=Depends(get_current_user),
):
    chat = (
        db.query(models.Chat)
        .filter(models.Chat.id == chat_id, models.Chat.is_deleted == False)
        .first()
    )
    if not chat:
        raise HTTPException(status_code=404, detail="Чат не найден")

    _ensure_chat_admin(db, chat, current_user.id)

    if not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Можно загружать только изображения")

    ext = os.path.splitext(file.filename)[1] or ".png"
    filename = f"chat_avatar_{chat_id}{ext}"
    save_dir = os.path.join(MEDIA_ROOT, "chat_avatars")
    os.makedirs(save_dir, exist_ok=True)
    save_path = os.path.join(save_dir, filename)

    with open(save_path, "wb") as f:
        f.write(await file.read())

    chat.avatar_url = f"/media/chat_avatars/{filename}"
    db.add(chat)
    db.commit()
    db.refresh(chat)

    return schemas.ChatOut(
        id=chat.id,
        type=chat.type,
        title=chat.title,
        avatar_url=chat.avatar_url,
        last_message_preview=None,
        last_message_at=chat.updated_at,
    )


# ---------- WebSocket endpoint ----------


@router.websocket("/ws/{chat_id}")
async def chat_websocket(
        websocket: WebSocket,
        chat_id: int,
        token: str,
        db: Session = Depends(get_db),
):
    payload = decode_access_token(token)
    if not payload or "sub" not in payload:
        await websocket.close(code=1008)
        return

    user_id = int(payload["sub"])
    user = (
        db.query(models.User)
        .filter(models.User.id == user_id, models.User.is_active == True)
        .first()
    )
    if not user:
        await websocket.close(code=1008)
        return

    participant = (
        db.query(models.ChatParticipant)
        .filter(
            models.ChatParticipant.chat_id == chat_id,
            models.ChatParticipant.user_id == user_id,
        )
        .first()
    )
    if not participant:
        await websocket.close(code=1008)
        return

    chat = (
        db.query(models.Chat)
        .filter(models.Chat.id == chat_id, models.Chat.is_deleted == False)
        .first()
    )
    if not chat:
        await websocket.close(code=1008)
        return

    await manager.connect(chat_id, user_id, websocket)

    try:
        while True:
            data = await websocket.receive_json()
            event_type = data.get("type", "message")

            if event_type == "typing":
                is_typing = bool(data.get("is_typing"))
                await manager.broadcast(
                    chat_id,
                    {
                        "event": "typing",
                        "chat_id": chat_id,
                        "user_id": user_id,
                        "is_typing": is_typing,
                    },
                )
                continue

            if event_type == "message":
                payload_obj = schemas.MessageCreate(
                    type=data.get("message_type", data.get("type", MessageTypeEnum.text)),
                    content=data.get("content"),
                    media_url=data.get("media_url"),
                    media_type=data.get("media_type"),
                )

                if chat.type == models.ChatTypeEnum.channel and not participant.is_admin:
                    continue

                msg = _create_message_and_notify(db, chat, user, payload_obj)
                serialized = _serialize_message(msg, current_user_id=user_id)
                await manager.broadcast(chat_id, {"event": "message", **serialized})
    except WebSocketDisconnect:
        manager.disconnect(chat_id, websocket)