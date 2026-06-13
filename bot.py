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
    "entries": [],
    "current_index": -1,
    "scores": {},
    "owner_names": {},
    "channel_id": None,
    "voting_message": None,
}

VOTE_DURATION = 30


class VoteView(discord.ui.View):
    def __init__(self, entry: dict):
        super().__init__(timeout=VOTE_DURATION)
        self.entry = entry
        self.votes = defaultdict(int)
        self.voted = set()

        for i in range(1, 6):
            btn = discord.ui.Button(
                label="⭐" * i,
                style=discord.ButtonStyle.secondary,
                custom_id=f"vote_{i}"
            )
            btn.callback = self.make_callback(i)
            self.add_item(btn)

    def make_callback(self, stars: int):
        async def callback(interaction: discord.Interaction):
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

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True

        total = sum(s * c for s, c in self.votes.items())
        count = sum(self.votes.values())

        oid = self.entry["owner_id"]
        competition["scores"][oid] = competition["scores"].get(oid, 0) + total
        competition["owner_names"][oid] = self.entry["owner_name"]

        embed = build_vote_embed(self.entry, total, count, finished=True)
        if competition["voting_message"]:
            try:
                await competition["voting_message"].edit(embed=embed, view=self)
            except:
                pass

        await next_entry()


def build_vote_embed(entry, total=0, count=0, finished=False):
    idx = competition["current_index"] + 1
    total_entries = len(competition["entries"])

    embed = discord.Embed(
        title="🎨 مسابقة الرسم — صوّت الآن!",
        description=f"الصورة **{idx}** من **{total_entries}**",
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
        embed.set_footer(text=f"⏳ {VOTE_DURATION} ثانية للتصويت")

    return embed


async def next_entry():
    competition["current_index"] += 1
    idx = competition["current_index"]

    if idx >= len(competition["entries"]):
        await end_competition()
        return

    channel = bot.get_channel(competition["channel_id"])
    entry = competition["entries"][idx]

    embed = build_vote_embed(entry)
    view = VoteView(entry)
    msg = await channel.send(f"🎨 <@{entry['owner_id']}>", embed=embed, view=view)
    competition["voting_message"] = msg


async def end_competition():
    channel = bot.get_channel(competition["channel_id"])
    scores = competition["scores"]
    names = competition["owner_names"]

    if not scores:
        await channel.send("❌ لا توجد نتائج.")
        competition["active"] = False
        return

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
    competition["current_index"] = -1


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
    competition["current_index"] = -1
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
        f"وقت التصويت لكل صورة: **{VOTE_DURATION} ثانية**\n"
        f"استعدوا! 🎨"
    )
    await asyncio.sleep(3)
    await next_entry()


@bot.command(name="الغ")
@commands.has_permissions(manage_messages=True)
async def cancel_comp(ctx):
    competition["active"] = False
    competition["entries"] = []
    competition["scores"] = {}
    competition["current_index"] = -1
    await ctx.send("🛑 تم إلغاء المسابقة.")


@bot.event
async def on_ready():
    print(f"✅ البوت شغال: {bot.user}")


bot.run(TOKEN)
