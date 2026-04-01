from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List

from app.database import get_db
from app.dependencies import get_current_user_id
from app.repositories.chapter_repo import ChapterRepository
from app.repositories.chapter_content_repo import ChapterContentRepository
from app.schemas.chapter import ChapterCreate, ChapterUpdate, ChapterRead
from app.schemas.chapter_content import ChapterContentUpdate, ChapterContentRead
from app.schemas.common import ApiResponse

router = APIRouter()


@router.get("/{novel_id}/chapters", response_model=ApiResponse[List[ChapterRead]])
async def list_chapters(
    novel_id: int,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    # Verify novel ownership through service
    from app.services.novel_service import NovelService
    await NovelService(db).get_novel(novel_id, user_id)

    chapters = await ChapterRepository(db).get_by_novel(novel_id)
    return ApiResponse(data=chapters)


@router.post("/{novel_id}/chapters", response_model=ApiResponse[ChapterRead], status_code=201)
async def create_chapter(
    novel_id: int,
    data: ChapterCreate,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    from app.services.novel_service import NovelService
    await NovelService(db).get_novel(novel_id, user_id)

    chapter = await ChapterRepository(db).create(
        title=data.title,
        chapter_number=data.chapter_number,
        synopsis=data.synopsis,
        novel_id=novel_id,
    )
    await db.commit()
    return ApiResponse(data=chapter)


@router.patch("/{novel_id}/chapters/{chapter_id}", response_model=ApiResponse[ChapterRead])
async def update_chapter(
    novel_id: int,
    chapter_id: int,
    data: ChapterUpdate,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    from app.services.novel_service import NovelService
    await NovelService(db).get_novel(novel_id, user_id)

    repo = ChapterRepository(db)
    chapter = await repo.get(chapter_id)
    if not chapter or chapter.novel_id != novel_id:
        from fastapi import HTTPException, status
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chapter not found")

    update_data = data.model_dump(exclude_unset=True)
    chapter = await repo.update(chapter, **update_data)
    await db.commit()
    return ApiResponse(data=chapter)


@router.delete("/{novel_id}/chapters/{chapter_id}", status_code=204)
async def delete_chapter(
    novel_id: int,
    chapter_id: int,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    from app.services.novel_service import NovelService
    await NovelService(db).get_novel(novel_id, user_id)

    repo = ChapterRepository(db)
    chapter = await repo.get(chapter_id)
    if not chapter or chapter.novel_id != novel_id:
        from fastapi import HTTPException, status
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chapter not found")

    await repo.delete(chapter)
    await db.commit()


@router.get("/{novel_id}/chapters/{chapter_id}/content", response_model=ApiResponse[ChapterContentRead])
async def get_chapter_content(
    novel_id: int,
    chapter_id: int,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    from app.services.novel_service import NovelService
    await NovelService(db).get_novel(novel_id, user_id)

    repo = ChapterRepository(db)
    chapter = await repo.get(chapter_id)
    if not chapter or chapter.novel_id != novel_id:
        from fastapi import HTTPException, status
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chapter not found")

    content_repo = ChapterContentRepository(db)
    content = await content_repo.get_latest(chapter_id)
    if not content:
        from fastapi import HTTPException, status
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chapter content not found")

    return ApiResponse(data=content)


@router.patch("/{novel_id}/chapters/{chapter_id}/content", response_model=ApiResponse[ChapterContentRead])
async def update_chapter_content(
    novel_id: int,
    chapter_id: int,
    data: ChapterContentUpdate,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    from app.services.novel_service import NovelService
    await NovelService(db).get_novel(novel_id, user_id)

    repo = ChapterRepository(db)
    chapter = await repo.get(chapter_id)
    if not chapter or chapter.novel_id != novel_id:
        from fastapi import HTTPException, status
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chapter not found")

    content_repo = ChapterContentRepository(db)
    content = await content_repo.get_latest(chapter_id)

    update_data = data.model_dump(exclude_unset=True)
    if 'content' in update_data and update_data['content']:
        update_data['word_count'] = len(update_data['content'])

    if content:
        # Update existing content
        content = await content_repo.update(content, **update_data)
    else:
        # Create new content
        content = await content_repo.create(
            chapter_id=chapter_id,
            word_count=update_data.get('word_count', 0),
            **update_data
        )

    await db.commit()
    return ApiResponse(data=content)
