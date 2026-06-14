import discord
from discord.ext import commands
import asyncio
import os
from dotenv import load_dotenv
from collections import defaultdict

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

competition = {
    "active": False,
    "entries": [],          # [{"owner_id", "owner_name", "image_url"}]
    "scores": {},            # {owner_id: total_stars}
    "owner_names": {},        # {owner_id: owner_name}
    "channel_id": None,
    "vote_views": [],         # كل الـ views النشطة
}

EVENT_DURATION = 48 * 60 * 60  # 48 ساعة بالثواني


class VoteView(discord.ui.View):
    def __init__(self, entry: dict):
        super().__init__(timeout=None)  # بدون timeout فردي، الإغلاق جماعي بعد 48 ساعة
        self.entry = entry
        self.votes = defaultdict(int)
        self.voted = set()
        self.message = None

        for i in range(1, 6):
            btn = discord.ui.Button(
                label="⭐" * i,
                style=discord.ButtonStyle.secondary,
                custom_id=f"vote_{entry['owner_id']}_{i}"
            )
            btn.callback = self.make_callback(i)
            self.add_item(btn)

    def make_callback(self, stars: int):
        async def callback(interaction: discord.Interaction):
            if not competition["active"]:
                await interaction.response.send_message(
                    "❌ انتهت المسابقة، لا يمكن التصويت.", ephemeral=True
                )
                return

            uid = interaction.user.id
            if uid in self.voted:
                await interaction.response.send_message(
                    "❌ لقد صوّتت بالفعل!", ephemeral=True
                )
                return

            self.voted.add(uid)
            self.votes[stars] += 1
            total = sum(s * c for s, c in self.votes.items())
            count = sum(self.votes.values())

            await interaction.response.send_message(
                f"✅ تم تسجيل تقييمك **{'⭐' * stars}**!", ephemeral=True
            )
            embed = build_vote_embed(self.entry, total, count)
            await interaction.message.edit(embed=embed, view=self)

        return callback

    def finalize(self):
        """يُستدعى عند انتهاء المسابقة لحساب النقاط النهائية"""
        total = sum(s * c for s, c in self.votes.items())
        count = sum(self.votes.values())

        oid = self.entry["owner_id"]
        competition["scores"][oid] = competition["scores"].get(oid, 0) + total
        competition["owner_names"][oid] = self.entry["owner_name"]

        for item in self.children:
            item.disabled = True

        return total, count


def build_vote_embed(entry, total=0, count=0, finished=False):
    embed = discord.Embed(
        title="🎨 مسابقة الرسم — صوّت الآن!",
        color=discord.Color.green() if finished else discord.Color.gold()
    )
    embed.add_field(name="الرسام", value=f"<@{entry['owner_id']}>", inline=False)
    embed.set_image(url=entry["image_url"])

    if finished:
        embed.add_field(
            name="⏱️ انتهى التصويت",
            value=f"النقاط: **{total} ⭐** | المصوّتون: **{count}**",
            inline=False
        )
    else:
        embed.add_field(
            name="⭐ المجموع حتى الآن",
            value=f"**{total}** من **{count}** مصوّت",
            inline=False
        )
        embed.set_footer(text="⏳ التصويت مفتوح لمدة 48 ساعة")

    return embed


async def end_competition():
    channel = bot.get_channel(competition["channel_id"])

    # إغلاق كل أزرار التصويت وحساب النقاط النهائية
    for view in competition["vote_views"]:
        total, count = view.finalize()
        embed = build_vote_embed(view.entry, total, count, finished=True)
        if view.message:
            try:
                await view.message.edit(embed=embed, view=view)
            except:
                pass

    scores = competition["scores"]

    if not scores:
        await channel.send("❌ لا توجد نتائج.")
    else:
        sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        medals = ["🥇", "🥈", "🥉"]
        lines = []
        for i, (uid, pts) in enumerate(sorted_scores):
            medal = medals[i] if i < 3 else f"**#{i+1}**"
            lines.append(f"{medal} <@{uid}> — **{pts} ⭐**")

        embed = discord.Embed(
            title="🏆 النتائج النهائية",
            description="\n".join(lines),
            color=discord.Color.gold()
        )
        embed.set_footer(text="شكراً لجميع المشاركين! 🎨")
        await channel.send(embed=embed)

    competition["active"] = False
    competition["entries"] = []
    competition["scores"] = {}
    competition["owner_names"] = {}
    competition["vote_views"] = []


# ───── الأوامر ─────

@bot.command(name="مسابقة")
@commands.has_permissions(manage_messages=True)
async def start_comp(ctx):
    if competition["active"]:
        await ctx.send("❌ توجد مسابقة نشطة!")
        return
    competition["entries"] = []
    competition["scores"] = {}
    competition["owner_names"] = {}
    competition["vote_views"] = []
    competition["channel_id"] = ctx.channel.id
    await ctx.send(
        "✅ **جاهز لاستقبال الصور!**\n"
        "أضف الصور بالأمر: `!اضف @اسم` مع إرفاق الصورة\n"
        "عند الانتهاء اكتب `!ابدأ`"
    )


@bot.command(name="اضف")
@commands.has_permissions(manage_messages=True)
async def add_entry(ctx, member: discord.Member):
    if competition["channel_id"] != ctx.channel.id:
        await ctx.send("❌ استخدم القناة الصحيحة.")
        return
    if competition["active"]:
        await ctx.send("❌ المسابقة بدأت، لا يمكن الإضافة.")
        return
    if not ctx.message.attachments:
        await ctx.send("❌ أرفق صورة مع الأمر.")
        return

    attachment = ctx.message.attachments[0]
    if not any(attachment.filename.lower().endswith(ext)
               for ext in [".png", ".jpg", ".jpeg", ".gif", ".webp"]):
        await ctx.send("❌ الملف ليس صورة.")
        return

    competition["entries"].append({
        "owner_id": member.id,
        "owner_name": member.display_name,
        "image_url": attachment.url
    })
    await ctx.send(
        f"✅ تمت إضافة صورة **{member.display_name}** "
        f"— الصورة رقم **{len(competition['entries'])}**"
    )


@bot.command(name="ابدأ")
@commands.has_permissions(manage_messages=True)
async def begin(ctx):
    if competition["channel_id"] != ctx.channel.id:
        return
    if not competition["entries"]:
        await ctx.send("❌ لم تضف أي صور بعد.")
        return
    if competition["active"]:
        await ctx.send("❌ المسابقة شغّالة.")
        return

    competition["active"] = True

    await ctx.send(
        f"🎉 **انطلقت المسابقة!**\n"
        f"عدد الصور: **{len(competition['entries'])}**\n"
        f"⏳ التصويت مفتوح لمدة **48 ساعة**\n"
        f"استعدوا! 🎨"
    )
    await asyncio.sleep(2)

    # إرسال كل الصور دفعة واحدة
    for entry in competition["entries"]:
        embed = build_vote_embed(entry)
        view = VoteView(entry)
        msg = await ctx.send(f"🎨 <@{entry['owner_id']}>", embed=embed, view=view)
        view.message = msg
        competition["vote_views"].append(view)
        await asyncio.sleep(1)  # تجنب الـ rate limit

    # انتظار 48 ساعة ثم إعلان النتائج
    await asyncio.sleep(EVENT_DURATION)

    if competition["active"]:
        await end_competition()


@bot.command(name="الغ")
@commands.has_permissions(manage_messages=True)
async def cancel_comp(ctx):
    competition["active"] = False
    competition["entries"] = []
    competition["scores"] = {}
    competition["owner_names"] = {}
    competition["vote_views"] = []
    await ctx.send("🛑 تم إلغاء المسابقة.")


@bot.command(name="انهي")
@commands.has_permissions(manage_messages=True)
async def force_end(ctx):
    if not competition["active"]:
        await ctx.send("❌ لا توجد مسابقة نشطة.")
        return
    await ctx.send("⏹️ تم إنهاء المسابقة يدوياً، جاري حساب النتائج...")
    await end_competition()


@bot.event
async def on_ready():
    print(f"✅ البوت شغال: {bot.user}")


bot.run(TOKEN)
