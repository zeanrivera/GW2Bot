import asyncio
import collections
import re
import time

import discord
from discord.ext import commands
from pymongo import ReplaceOne
from pymongo.errors import BulkWriteError

from .exceptions import APIKeyError


class DatabaseMixin:
    @commands.group(case_insensitive=True)
    @commands.is_owner()
    async def database(self, ctx):
        """Commands related to DB management"""
        if ctx.invoked_subcommand is None:
            await ctx.send_help()
            return

    @database.command(name="create")
    async def db_create(self, ctx):
        """Create a new database
        """
        await self.rebuild_database()

    @database.command(name="statistics")
    async def db_stats(self, ctx):
        """Some statistics   """
        result = await self.bot.database.users.count_documents({
            "cogs.GuildWars2.key": {
                "$ne": None
            }
        }, self)
        await ctx.send("{} registered users".format(result))

    async def get_title(self, title_id):
        try:
            results = await self.db.titles.find_one({"_id": title_id})
            title = results["name"]
        except KeyError:
            return ""
        return title

    async def get_world_name(self, wid):
        try:
            doc = await self.db.worlds.find_one({"_id": wid})
            name = doc["name"]
        except KeyError:
            name = None
        return name

    async def get_world_id(self, world):
        world = re.escape(world)
        world = "^" + world + "$"
        search = re.compile(world, re.IGNORECASE)
        if world is None:
            return None
        doc = await self.db.worlds.find_one({"name": search})
        if not doc:
            return None
        return doc["_id"]

    async def fetch_statname(self, item):
        statset = await self.db.itemstats.find_one({"_id": item})
        try:
            name = statset["name"]
        except:
            name = ""
        return name

    async def fetch_item(self, item):
        return await self.db.items.find_one({"_id": item})

    async def fetch_key(self, user, scopes=None):
        doc = await self.bot.database.get_user(user, self)
        if not doc or "key" not in doc or not doc["key"]:
            raise APIKeyError(
                "No API key associated with {.mention}. "
                "Add your key using `$key add` command. If you don't know "
                "how, the command includes a tutorial.".format(user))
        if scopes:
            missing = []
            for scope in scopes:
                if scope not in doc["key"]["permissions"]:
                    missing.append(scope)
            if missing:
                missing = ", ".join(missing)
                raise APIKeyError(
                    "{.mention}, your API key is missing the following "
                    "permissions to use this command: `{}`\nConsider adding "
                    "a new key with those permissions "
                    "checked".format(user, missing))
        return doc["key"]

    async def cache_dailies(self):
        try:
            results = await self.call_api("achievements/daily")
            await self.cache_endpoint("achievements")
        except:
            return
        try:
            doc = {}
            for category, dailies in results.items():
                daily_list = []
                for daily in dailies:
                    if not daily["level"]["max"] == 80:
                        continue
                    daily_doc = await self.db.achievements.find_one({
                        "_id":
                        daily["id"]
                    })
                    if not daily_doc:
                        continue
                    name = daily_doc["name"]
                    if category == "fractals":
                        if name.startswith(
                                "Daily Tier"
                        ) and not name.startswith("Daily Tier 4"):
                            continue
                    daily_list.append(name)
                doc[category] = sorted(daily_list)
            doc["psna"] = [self.get_psna()]
            doc["psna_later"] = [self.get_psna(offset_days=1)]
            await self.bot.database.set_cog_config(self,
                                                   {"cache.dailies": doc})
        except Exception as e:
            self.log.exception("Exception caching dailies: ", exc_info=e)

    async def cache_raids(self):
        raids = []
        raids_index = await self.call_api("raids")
        for raid in raids_index:
            raids.append(await self.call_api("raids/" + raid))
        await self.bot.database.set_cog_config(self, {"cache.raids": raids})

    async def get_raids(self):
        config = await self.bot.database.get_cog_config(self)
        return config["cache"].get("raids")

    async def cache_endpoint(self, endpoint, all_at_once=False):
        async def bulk_write(item_group):
            requests = []
            for item in itemgroup:
                item["_id"] = item.pop("id")
                requests.append(
                    ReplaceOne({
                        "_id": item["_id"]
                    }, item, upsert=True))
            try:
                await self.db[endpoint].bulk_write(requests)
            except BulkWriteError as e:
                self.log.exception(
                    "BWE while caching {}".format(endpoint), exc_info=e)

        items = await self.call_api(endpoint)
        if not all_at_once:
            counter = 0
            total = len(items)
            while True:
                percentage = (counter / total) * 100
                print("Progress: {0:.1f}%".format(percentage))
                ids = ",".join(str(x) for x in items[counter:counter + 200])
                if not ids:
                    print("{} done".format(endpoint))
                    break
                itemgroup = await self.call_api("{}?ids={}".format(
                    endpoint, ids))
                await bulk_write(itemgroup)
                counter += 200
        else:
            itemgroup = await self.call_api("{}?ids=all".format(endpoint))
            await bulk_write(itemgroup)

    async def rebuild_database(self):
        start = time.time()
        self.bot.available = False
        await self.bot.change_presence(
            activity=discord.Game(name="Rebuilding API cache"),
            status=discord.Status.dnd)
        endpoints = [["items"], ["achievements"], ["itemstats", True], [
            "titles", True
        ], ["recipes"], ["skins"], ["currencies", True], ["skills", True],
                     ["specializations", True], ["traits", True],
                     ["worlds", True], ["minis", True]]
        for e in endpoints:
            try:
                await self.cache_endpoint(*e)
            except:
                msg = "Caching {} failed".format(e)
                self.log.warn(msg)
                owner = self.bot.get_user(self.bot.owner_id)
                await owner.send(msg)
        await self.db.items.create_index("name")
        await self.db.achievements.create_index("name")
        await self.db.titles.create_index("name")
        await self.db.recipes.create_index("output_item_id")
        await self.db.skins.create_index("name")
        await self.db.currencies.create_index("name")
        await self.db.skills.create_index("name")
        await self.db.worlds.create_index("name")
        await self.cache_raids()
        end = time.time()
        await self.bot.change_presence()
        self.bot.available = True
        print("Done")
        self.log.info(
            "Database done! Time elapsed: {} seconds".format(end - start))

    async def itemname_to_id(self,
                             destination,
                             item,
                             user,
                             *,
                             flags=[],
                             filters={},
                             database="items",
                             group_duplicates=False):  # TODO cleanup
        def consolidate_duplicates(items):
            unique_items = collections.OrderedDict()
            for item in items:
                item_tuple = item["name"], item["rarity"]
                if item_tuple not in unique_items:
                    unique_items[item_tuple] = []
                unique_items[item_tuple].append(item["_id"])
            unique_list = []
            for k, v in unique_items.items():
                unique_list.append({"name": k[0], "rarity": k[1], "ids": v})
            return unique_list

        def check(m):
            if isinstance(destination,
                          (discord.abc.User, discord.abc.PrivateChannel)):
                chan = isinstance(m.channel, discord.abc.PrivateChannel)
            else:
                chan = m.channel == destination.channel
            return m.author == user and chan

        item_sanitized = re.escape(item)
        search = re.compile(item_sanitized + ".*", re.IGNORECASE)
        query = {"name": search, "flags": {"$nin": flags}, **filters}
        number = await self.db[database].count_documents(query)
        if not number:
            await destination.send(
                "Your search gave me no results, sorry. Check for "
                "typos.\nAlways use singular forms, e.g. Legendary Insight")
            return None
        cursor = self.db[database].find(query)
        if number > 25:
            await destination.send("Your search gave me {} item results. "
                                   "Try exact match "
                                   "search? `Y/N`".format(number))
            try:
                answer = await self.bot.wait_for(
                    "message", timeout=120, check=check)
            except asyncio.TimeoutError:
                return None
            if answer.content.lower() != "y":
                return
            exact_match = "^" + item_sanitized + "$"
            search = re.compile(exact_match, re.IGNORECASE)
            query["name"] = search
            number = await self.db[database].count_documents(query)
            cursor = self.db[database].find()
            if not number:
                await destination.send(
                    "Your search gave me no results, sorry. Check for "
                    "typos.\nAlways use singular forms, e.g. Legendary Insight"
                )
                return None
            if number > 25:
                await destination.send(
                    "Your search gave me {} item results. "
                    "Please be more specific".format(number))
                return None
        items = []
        async for item in cursor:
            items.append(item)
        items.sort(key=lambda i: i["name"])
        longest = len(max([item["name"] for item in items], key=len))
        msg = [
            "Which one of these interests you? Simply type it's number "
            "into the chat now:```ml",
            "INDEX    NAME {}RARITY".format(" " * (longest)),
            "-----|------{}|-------".format("-" * (longest))
        ]

        if group_duplicates:
            distinct_items = consolidate_duplicates(items)
        else:
            for item in items:
                item["ids"] = [item["_id"]]
            distinct_items = items
        if number != 1:
            for c, m in enumerate(distinct_items, 1):
                msg.append("  {} {}| {} {}| {}".format(
                    c, " " * (2 - len(str(c))), m["name"].upper(),
                    " " * (4 + longest - len(m["name"])), m["rarity"]))
            msg.append("```")
            message = await destination.send("\n".join(msg))
            try:
                answer = await self.bot.wait_for(
                    "message", timeout=120, check=check)
            except asyncio.TimeoutError:
                await message.edit(content="No response in time")
                return None
            try:
                num = int(answer.content) - 1
                choice = distinct_items[num]
            except:
                await message.edit(content="That's not a number in the list")
                return None
            try:
                await message.delete()
                await answer.delete()
            except:
                pass
        else:
            choice = distinct_items[0]

        for item in items:
            if item["_id"] in choice["ids"]:
                if item["type"] == "UpgradeComponent":
                    choice["is_upgrade"] = True

        return choice

    async def selection_menu(self,
                             ctx,
                             cursor,
                             number,
                             *,
                             filter_callable=None):
        # TODO implement fields

        def check(m):
            return m.channel == ctx.channel and m.author == ctx.author

        if not number:
            await ctx.send(
                "Your search gave me no results, sorry. Check for "
                "typos.\nAlways use singular forms, e.g. Legendary Insight")
            return None
        if number > 25:
            await ctx.send("Your search gave me {} item results. "
                           "Please be more specific".format(number))
            return None
        items = []
        async for item in cursor:
            items.append(item)
        key = "name"
        if filter_callable:
            items = filter_callable(items)
        number = len(items)
        items.sort(key=lambda i: i[key])
        longest = len(max([item[key] for item in items], key=len))
        key_pos = (longest + 2) // 2 - 2
        header = "INDEX{} {}{}".format(" " * key_pos, key.upper(),
                                       " " * (longest - 2 - key_pos))
        msg = [
            "Which one of these interests you? Simply type it's number "
            "into the chat now:```ml", header,
            "-----|-{}-".format("-" * longest)
        ]
        if number != 1:
            for c, m in enumerate(items, 1):
                msg.append("  {} {}| {} {}".format(
                    c, " " * (2 - len(str(c))), m[key].upper(),
                    " " * (longest - len(m[key]))))
            msg.append("```")
            message = await ctx.send("\n".join(msg))
            try:
                answer = await self.bot.wait_for(
                    "message", timeout=120, check=check)
            except asyncio.TimeoutError:
                await message.edit(content="No response in time")
                return None
            try:
                num = int(answer.content) - 1
                choice = items[num]
            except:
                await message.edit(content="That's not a number in the list")
                return None
            try:
                await message.delete()
                await answer.delete()
            except:
                pass
        else:
            choice = items[0]
        return choice
