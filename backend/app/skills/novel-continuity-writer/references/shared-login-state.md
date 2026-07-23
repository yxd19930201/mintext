# 番茄登录态共享模板说明

## 原则

- 可以共享的是 `state.template.json`
- 不能共享的是每个项目真实登录后的 `state.json`

## 为什么不能直接共享真实 `state.json`

- 真实 `state.json` 是 Playwright `storage_state`
- 里面包含 cookie 和 localStorage，会直接携带番茄登录会话
- 放进 skill 后，所有小说项目都会共用同一份敏感登录态
- 这既不安全，也容易把一个项目的异常状态带到别的项目

## 推荐结构

Skill 内公共参考文件：

```text
references/state.template.json
```

项目内实际文件：

```text
.runtime/fanqie/state.template.json
.runtime/fanqie/state.json
```

## 用法

1. 初始化小说项目时，自动生成 `.runtime/fanqie/state.template.json`
2. 它只提供空结构：

```json
{
  "cookies": [],
  "origins": []
}
```

3. 真正可发布的登录态仍然由：

```powershell
python tools/novel_publish.py login
```

写入项目自己的 `.runtime/fanqie/state.json`

4. 如果已有旧项目能正常登录，只复用它的登录流程或脚本思路，不直接复用其真实 `state.json`

## 结论

如果要“所有小说项目一起使用”，应该共用模板和登录流程，不应该共用真实登录态文件。
