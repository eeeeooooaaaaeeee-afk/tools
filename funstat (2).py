# meta developer: @lololo000yt, fork by @kchemniy_modules
# scope: hikka_only

import asyncio
import random
import base64
import aiohttp
import json
import re
from telethon import events, errors, types, functions
from .. import loader, utils

@loader.tds
class FunStatFarmMod(loader.Module):
    """Модуль автоматического взаимодействия с сервисами статистики"""
    
    strings = {
        "name": "FunStatFarm",
        "started": "🚀 <b>Цикл активности запущен!</b>",
        "stopped": "🛑 <b>Цикл активности остановлен.</b>",
        "changed": "🔄 <b>Зеркало обновлено:</b> <code>{}</code>",
        "verifying": "🛡 <b>Обнаружена визуальная проверка. Анализирую...</b>",
        "solved": "🤖 <b>Проверка пройдена. Выбор: {}</b>",
        "error_api": "❌ <b>Не удалось получить юзернейм ни с одного сервера.</b>",
        "error_ai": "❌ <b>Ошибка внешнего обработчика: {}</b>",
        "target_dead": "💀 <b>Сервис недоступен (аккаунт удален), ищу новое зеркало...</b>",
        "cfg_target": "Юзернейм целевого сервиса (оставьте пустым для автопоиска)",
        "cfg_interval": "Частота взаимодействия в секундах"
    }

    active = False
    task = None
    last_media_id = None
    pending_bot = None

    def __init__(self):
        super().__init__()
        self.config = loader.ModuleConfig(
            loader.ConfigValue(
                "target_bot",
                "",
                lambda: self.strings("cfg_target")
            ),
            loader.ConfigValue(
                "interval",
                15,
                lambda: self.strings("cfg_interval")
            )
        )
        self.active = False
        self.task = None
        self.last_media_id = None
        self.pending_bot = None

    async def client_ready(self, client, db):
        self.client = client


    async def _auto_delete(self, msg, delay: int = 5):
        """Удалить сообщение через delay секунд (тихо, без ошибок)."""
        await asyncio.sleep(delay)
        try:
            await msg.delete()
        except Exception:
            try:
                peer = getattr(msg, "peer_id", None) or getattr(msg, "chat_id", None)
                if peer is not None:
                    await self.client.delete_messages(peer, [msg.id], revoke=True)
            except Exception:
                pass

    async def _finish(self, message, text, **kwargs):
        """Ответить редактированием команды и удалить её через 5 секунд."""
        edited = await message.edit(text, **kwargs)
        asyncio.create_task(self._auto_delete(edited, 5))
        return edited

    async def _get_new_bot(self):
        """Получение нового юзернейма через API"""
        urls = [
            "https://funstat.info/api/v1/bot/random",
            "http://telelog.info/api/v1/bot/random",
            "http://telelog.org/api/v1/bot/random"
        ]
        random.shuffle(urls)
        
        timeout = aiohttp.ClientTimeout(total=15)
        
        async with aiohttp.ClientSession(timeout=timeout) as session:
            for url in urls:
                try:
                    async with session.get(url) as resp:
                        if resp.status == 200:
                            text = await resp.text()
                            try:
                                data = json.loads(text)
                            except json.JSONDecodeError:
                                continue
                            bot = data.get("tag") or data.get("username")
                            if bot:
                                if not bot.startswith("@"):
                                    bot = "@" + bot
                                self.config["target_bot"] = bot
                                return bot
                except Exception:
                    continue
        return None

    async def _prepare_chat(self, peer):
        """Отключение уведомлений и перенос в архив"""
        try:
            entity = await self.client.get_entity(peer)
            await self.client(functions.account.UpdateNotifySettingsRequest(
                peer=types.InputNotifyPeer(peer=await self.client.get_input_entity(entity)),
                settings=types.InputPeerNotifySettings(mute_until=2147483647)
            ))
            await self.client(functions.folders.EditPeerFoldersRequest(
                folder_peers=[types.InputFolderPeer(peer=await self.client.get_input_entity(entity), folder_id=1)]
            ))
        except Exception:
            pass

    async def _solve_visual_test(self, message):
        """Логика прохождения проверки через AI"""
        try:
            media_bytes = await message.download_media(bytes)
            if not media_bytes:
                return False
            
            base64_image = base64.b64encode(media_bytes).decode('utf-8')
            
            buttons = []
            if message.buttons:
                for row in message.buttons:
                    for btn in row:
                        buttons.append(btn.text)
            
            if len(buttons) < 3:
                return False

            prompt = (
                f"Проанализируй текст с изображения и выбери наиболее подходящий эмодзи "
                f"из списка:\n"
                f"{buttons[0]}\n{buttons[1]}\n{buttons[2]}\n"
                f"В ответе напиши только выбранный эмодзи."
            )

            payload = {
                "model": "openai",
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
                        ]
                    }
                ]
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    'https://text.pollinations.ai/openai', 
                    json=payload, 
                    headers={'Content-Type': 'application/json'}
                ) as resp:
                    if resp.status == 200:
                        raw_text = await resp.text()
                        target_emoji = raw_text.strip().replace('"', '').replace("'", "").replace(".", "")
                        for row in message.buttons:
                            for btn in row:
                                if target_emoji in btn.text or btn.text in target_emoji:
                                    await btn.click()
                                    return target_emoji
        except Exception as e:
            await self.client.send_message("me", self.strings("error_ai").format(str(e)))
        return False

    @loader.command()
    async def funstart(self, message):
        """- запуск цикла активности"""
        if self.active:
            return await self._finish(message, "⚠️ Цикл уже запущен.")
        
        self.active = True
        self.task = asyncio.create_task(self.worker())
        return await self._finish(message, self.strings("started"))

    @loader.command()
    async def funstop(self, message):
        """- полная остановка цикла"""
        self.active = False
        if self.task:
            self.task.cancel()
            self.task = None
        return await self._finish(message, self.strings("stopped"))

    @loader.command()
    async def funchange(self, message):
        """- принудительное обновление рабочего зеркала"""
        arg = (utils.get_args_raw(message) or "").strip()
        if arg:
            bot = arg
            if not bot.startswith("@"):
                bot = "@" + bot

            await message.edit("🧪 <b>Проверяю бота...</b>")

            try:
                entity = await self.client.get_entity(bot)
                if isinstance(entity, types.User) and entity.deleted:
                    raise ValueError("Bot deleted")
            except Exception:
                return await self._finish(message, "❌ <b>Бот не валиден.</b>")

            sent = None
            resp = None
            try:
                async with self.client.conversation(bot, timeout=15) as conv:
                    sent = await conv.send_message("/menu")
                    await asyncio.sleep(1)
                    resp = await conv.get_response()
            except Exception:
                if sent is not None:
                    try:
                        await self.client.delete_messages(bot, [sent.id], revoke=True)
                    except Exception:
                        pass
                return await self._finish(message, "❌ <b>Бот не валиден.</b>")

            raw = getattr(resp, "raw_text", None) or getattr(resp, "message", None) or ""
            text = raw
            text = text.replace("\u200b", "").replace("\u200c", "").replace("\u200d", "").replace("\ufeff", "")
            text = text.replace("／", "/").replace("∕", "/").replace("╱", "/").replace("⧸", "/")
            text_l = text.lower()

            has_id = re.search(r"(?:^|\n)\s*[├┣]\s*id\s*:", text_l) is not None
            has_lang = re.search(r"(?:^|\n)\s*[├┣]\s*/lang\s*:", text_l) is not None
            has_diamond = "💠" in text
            valid = has_id and has_lang and has_diamond

            try:
                to_delete = [m.id for m in (sent, resp) if m is not None]
                if to_delete:
                    await self.client.delete_messages(bot, to_delete, revoke=True)
            except Exception:
                pass

            if not valid:
                self.pending_bot = bot
                return await self._finish(message,
                    "⚠️ <b>Не удалось подтвердить валидность бота по ответу.</b>\n"
                    "Хочешь всё равно добавить зеркало?\n"
                    "<code>.funyes</code> — добавить\n"
                    "<code>.funo</code> — не добавлять"
                )

            self.config["target_bot"] = bot
            await self._prepare_chat(bot)
            return await self._finish(message, "✅ <b>бот валиден</b>")

        await message.edit("🔄 <b>Ищу новое зеркало...</b>")
        new_bot = await self._get_new_bot()
        if new_bot:
            await self._prepare_chat(new_bot)
            return await self._finish(message, self.strings("changed").format(new_bot))
        else:
            return await self._finish(message, self.strings("error_api"))

    @loader.command()
    async def funhelp(self, message):
        """- показать список команд"""
        return await self._finish(message,
            "🧾 <b>Команды FunStatFarm:</b>\n"
            "<code>.funstart</code> — запуск цикла активности\n"
            "<code>.funstop</code> — остановка цикла\n"
            "<code>.funchange</code> — обновить зеркало (бота)\n"
            "<code>.funyes</code> — подтвердить добавление зеркала\n"
            "<code>.funo</code> — отменить добавление зеркала\n"
            "<code>.funhelp</code> — показать это сообщение"
        )

    @loader.command()
    async def funyes(self, message):
        """- подтвердить добавление зеркала"""
        if not self.pending_bot:
            return await self._finish(message, "ℹ️ <b>Нет зеркала, ожидающего подтверждения.</b>")

        bot = self.pending_bot
        self.pending_bot = None
        self.config["target_bot"] = bot
        await self._prepare_chat(bot)
        return await self._finish(message, f"✅ <b>Зеркало установлено:</b> <code>{bot}</code>")

    @loader.command()
    async def funo(self, message):
        """- отменить добавление зеркала"""
        self.pending_bot = None
        return await self._finish(message, "✅ <b>Ок, зеркало не добавляю.</b>")

    @loader.command()
    async def funact(self, message):
        """- показать статус модуля"""
        target = self.config["target_bot"] or "не установлен"
        pending = self.pending_bot or "нет"
        status = "🟢 активен" if self.active else "🔴 остановлен"
        last_id = self.last_media_id or "нет"

        return await self._finish(message,
            f"📊 <b>Статус FunStatFarm:</b>\n"
            f"• Цикл: {status}\n"
            f"• Зеркало: <code>{target}</code>\n"
            f"• Ожидающий: <code>{pending}</code>\n"
            f"• Последний media_id: <code>{last_id}</code>"
        )

    async def worker(self):
        search_bot = "@en_SearchBot"
        
        while self.active:
            try:
                target = self.config["target_bot"]
                
                if not target:
                    target = await self._get_new_bot()
                    if not target:
                        await asyncio.sleep(60)
                        continue
                    await self._prepare_chat(target)

                try:
                    entity = await self.client.get_entity(target)
                    if isinstance(entity, types.User) and entity.deleted:
                        raise ValueError("Bot deleted")
                except (ValueError, errors.RpcError):
                    await self.client.send_message("me", self.strings("target_dead"))
                    self.config["target_bot"] = "" 
                    continue

                try:
                    async for last_msg in self.client.iter_messages(target, limit=1):
                        if last_msg.photo and last_msg.buttons:
                            total_buttons = sum(len(row) for row in last_msg.buttons)
                            if total_buttons == 3:
                                await self.client.send_message("me", self.strings("verifying"))
                                solved = await self._solve_visual_test(last_msg)
                                if solved:
                                    await self.client.send_message("me", self.strings("solved").format(solved))
                                    await asyncio.sleep(5) 
                                continue 
                except Exception:
                    pass

                msgs = await self.client.get_messages(search_bot, limit=5)

                if msgs:
                    for msg in msgs:
                        if msg and msg.text:
                            raw = msg.text
                            text = raw
                            text = text.replace("\u200b", "").replace("\u200c", "").replace("\u200d", "").replace("\ufeff", "")
                            text = text.lower()

                            if (
                                "daily usage limit" in text
                                or "usage limit exceeded" in text
                                or "bot unresponsive" in text
                                or "unlock or try tomorrow" in text
                                or "limit exceeded" in text
                                or "try tomorrow" in text
                                or "unresponsive" in text
                            ):
                                await self.client.send_message(
                                    "me",
                                    f"⛔ <b>Ошибка @en_SearchBot:</b> {raw[:100]}... Цикл остановлен."
                                )
                                self.active = False
                                break
                    if not self.active:
                        break

                msg = msgs[0] if msgs else None
                if not msgs or not msg or not msg.buttons:
                    await self.client.send_message(search_bot, "/rand")
                    await asyncio.sleep(5)
                    continue

                msg = msgs[0]
                current_id = msg.media.to_dict().get('photo', {}).get('id') if msg.media else msg.text
                
                if current_id != self.last_media_id:
                    await self.client.send_message(
                        entity=target,
                        message=msg.text or "",
                        file=msg.media if msg.media else None,
                    )
                    self.last_media_id = current_id

                pushed = False
                if msg.buttons:
                    for row in msg.buttons:
                        for btn in row:
                            if "Change" in btn.text or "Next" in btn.text:
                                await btn.click()
                                pushed = True
                                break
                        if pushed:
                            break
                    
                    if not pushed:
                        try:
                            await msg.click(0)
                        except Exception:
                            pass

                await asyncio.sleep(self.config["interval"])

            except asyncio.CancelledError:
                break
            except Exception:
                await asyncio.sleep(10)
