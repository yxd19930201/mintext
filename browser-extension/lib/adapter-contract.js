// Generated from fanqie-core/fanqie_core/adapter_contract.json. Do not edit.
globalThis.MaliangFanqieContract = {
  "version": 5,
  "source": "playwright_fanqie_client",
  "pages": {
    "writer_home": "https://fanqienovel.com/main/writer",
    "book_manage": "https://fanqienovel.com/main/writer/book-manage",
    "chapter_manage": "https://fanqienovel.com/main/writer/chapter-manage/{book_id}?type=1",
    "publish_new": "https://fanqienovel.com/main/writer/{book_id}/publish/?enter_from=newchapter",
    "publish_edit": "https://fanqienovel.com/main/writer/{book_id}/publish/{chapter_id}?enter_from=edit"
  },
  "selectors": {
    "author_identity": [
      ".muye-header-user",
      ".slogin-user-avatar__info__name",
      "[class*='user-name']",
      "[class*='author-name']",
      "[class*='nickname']",
      ".account-name"
    ],
    "author_id": [
      "[data-author-id]",
      "[data-user-id]"
    ],
    "book_links": [
      "a[href*='chapter-manage/']"
    ],
    "book_nodes": [
      "[data-book-id]",
      "[data-bookid]"
    ],
    "book_name": [
      "input[placeholder*='作品名']",
      "input[placeholder*='书名']",
      "input[placeholder*='作品名称']",
      "input[name='book_name']"
    ],
    "cover_file": [
      "input[type='file']"
    ],
    "protagonist": [
      "input[placeholder*='主角名']",
      "input[placeholder*='主角']",
      "input[name*='protagonist']"
    ],
    "intro": [
      "textarea[placeholder*='简介']",
      "textarea[name='abstract']",
      "textarea[name='description']"
    ],
    "tag_selector": [
      ".select-view"
    ],
    "tag_modal": [
      ".category-modal"
    ],
    "tag_option": [
      ".category-choose-item-title"
    ],
    "chapter_number": [
      ".serial-editor-title-left input",
      ".left-input input",
      "input[name='chapter_number']"
    ],
    "chapter_title": [
      "input[placeholder*='标题']",
      "input[placeholder*='章节名']",
      "input.serial-editor-input-hint-area",
      "input[name='title']"
    ],
    "chapter_content": [
      ".ql-editor",
      ".ProseMirror[contenteditable='true']",
      ".ProseMirror",
      "[contenteditable='true']",
      "textarea[name='content']"
    ],
    "modal": [
      ".arco-modal-content",
      ".arco-modal",
      "[role='dialog']"
    ],
    "date": [
      "input[type='date']",
      "input[placeholder*='日期']"
    ],
    "time": [
      "input[type='time']",
      "input[placeholder*='时间']"
    ],
    "chapter_rows": [
      "tr",
      "li",
      "[class*='chapter']",
      "[class*='Chapter']"
    ]
  },
  "actions": {
    "create_book": [
      "创建作品",
      "新建作品",
      "创建新书",
      "创建书本"
    ],
    "tag_confirm": [
      "确认"
    ],
    "create_confirm": [
      "确认创建",
      "立即创建",
      "创建作品"
    ],
    "new_chapter": [
      "新建章节"
    ],
    "edit_chapter": [
      "编辑",
      "继续创作"
    ],
    "next": [
      "下一步"
    ],
    "basic_detection": [
      "仅基础检测",
      "基础检测"
    ],
    "submit_typo": [
      "提交"
    ],
    "cancel_risk": [
      "取消"
    ],
    "confirm_publish": [
      "确认发布"
    ],
    "schedule": [
      "定时发布"
    ],
    "next_page": [
      "下一页",
      "下页",
      "next"
    ]
  },
  "signals": {
    "login": [
      "请登录",
      "登录后继续",
      "验证码登录",
      "扫码登录",
      "登录/注册",
      "密码登录"
    ],
    "risk": [
      "验证码",
      "安全验证",
      "完成验证",
      "登录异常",
      "账号异常",
      "访问过于频繁"
    ],
    "publish_settings": [
      "是否使用AI",
      "是否使用 AI",
      "错别字未修改",
      "内容检测方式",
      "内容风险检测",
      "确认发布"
    ],
    "publish_success": [
      "定时发布成功",
      "发布成功",
      "提交成功",
      "发布完成",
      "已提交",
      "提交审核"
    ]
  },
  "status_words": {
    "rejected": [
      "审核失败",
      "审核未通过",
      "驳回",
      "违规"
    ],
    "reviewing": [
      "审核中",
      "待审核",
      "提交审核"
    ],
    "scheduled": [
      "定时",
      "待发布",
      "预计发布"
    ],
    "draft": [
      "草稿",
      "未发布"
    ],
    "published": [
      "已发布",
      "已上线",
      "发布成功"
    ]
  },
  "timeouts_ms": {
    "element": 20000,
    "dialog": 60000,
    "publish_result": 30000,
    "book_created": 30000,
    "poll": 250
  }
};
