import operator

import discord
from discord.ext import commands
from discord.ext.commands.cooldowns import BucketType

from .exceptions import APIBadRequest, APIError, APINotFound


class CommerceMixin:
    @commands.group(case_insensitive=True)
    async def tp(self, ctx):
        """Commands related to tradingpost"""
        if ctx.invoked_subcommand is None:
            await ctx.send_help()

    @tp.command(name="current")
    @commands.cooldown(1, 10, BucketType.user)
    async def tp_current(self, ctx, buys_sells):
        """Show current selling/buying transactions
        invoke with sells or buys

        Required permissions: tradingpost
        """
        user = ctx.author
        state = buys_sells.lower()
        endpoint = "commerce/transactions/current/" + state
        if state == "buys" or state == "sells":
            try:
                doc = await self.fetch_key(user, ["tradingpost"])
                results = await self.call_api(endpoint, key=doc["key"])
            except APIError as e:
                return await self.error_handler(ctx, e)
        else:
            return await ctx.send(
                "{0.mention}, Please us either 'sells' or 'buys' as parameter".
                format(user))
        data = discord.Embed(
            description='Current ' + state,
            colour=await self.get_embed_color(ctx))
        data.set_author(
            name='Transaction overview of {0}'.format(doc["account_name"]))
        data.set_thumbnail(
            url=("https://wiki.guildwars2.com/"
                 "images/thumb/d/df/Black-Lion-Logo.png/"
                 "300px-Black-Lion-Logo.png"))
        data.set_footer(text="Black Lion Trading Company")
        results = results[:20]  # Only display 20 most recent transactions
        item_id = ""
        dup_item = {}
        # Collect listed items
        for result in results:
            item_id += str(result["item_id"]) + ","
            if result["item_id"] not in dup_item:
                dup_item[result["item_id"]] = len(dup_item)
        # Get information about all items, doesn't matter if string ends with ,
        endpoint_listing = "commerce/listings?ids={0}".format(str(item_id))
        # Call API once for all items
        try:
            listings = await self.call_api(endpoint_listing)
        except APIBadRequest:
            return await ctx.send("{.mention} you don't have any ongoing "
                                  "transactions".format(user))
        except APIError as e:
            return await self.error_handler(ctx, e)

        for result in results:
            index = dup_item[result["item_id"]]
            price = result["price"]
            itemdoc = await self.fetch_item(result["item_id"])
            quantity = result["quantity"]
            item_name = itemdoc["name"]
            offers = listings[index][state]
            max_price = offers[0]["unit_price"]
            undercuts = 0
            op = operator.lt if state == "buys" else operator.gt
            for offer in offers:
                if op(offer["unit_price"], price):
                    break
                undercuts += offer["listings"]
            undercuts = "· Undercuts: {}".format(
                undercuts) if undercuts else ""
            if quantity == 1:
                total = ""
            else:
                total = " - Total: " + self.gold_to_coins(
                    ctx, quantity * price)
            data.add_field(
                name=item_name,
                value="{} x {}{}\nMax. offer: {} {}".format(
                    quantity, self.gold_to_coins(ctx, price), total,
                    self.gold_to_coins(ctx, max_price), undercuts),
                inline=False)

        try:
            await ctx.send(embed=data)
        except discord.HTTPException:
            await ctx.send("Need permission to embed links")

    @tp.command(name="price")
    @commands.cooldown(1, 15, BucketType.user)
    async def tp_price(self, ctx, *, item: str):
        """Check price of an item"""
        user = ctx.author
        flags = ["AccountBound", "SoulbindOnAcquire"]
        choice = await self.itemname_to_id(ctx, item, user, flags=flags)
        if not choice:
            return
        try:
            commerce = 'commerce/prices/'
            choiceid = str(choice["_id"])
            endpoint = commerce + choiceid
            results = await self.call_api(endpoint)
        except APINotFound as e:
            return await ctx.send("{0.mention}, This item isn't on the TP."
                                  "".format(user))
        except APIError as e:
            return await self.error_handler(ctx, e)
        buyprice = results["buys"]["unit_price"]
        sellprice = results["sells"]["unit_price"]
        itemname = choice["name"]
        level = str(choice["level"])
        rarity = choice["rarity"]
        itemtype = self.gamedata["items"]["types"][choice["type"]].lower()
        description = "A level {} {} {}".format(level, rarity.lower(),
                                                itemtype.lower())
        if buyprice != 0:
            buyprice = self.gold_to_coins(ctx, buyprice)
        if sellprice != 0:
            sellprice = self.gold_to_coins(ctx, sellprice)
        if buyprice == 0:
            buyprice = 'No buy orders'
        if sellprice == 0:
            sellprice = 'No sell orders'
        data = discord.Embed(
            title=itemname,
            description=description,
            colour=self.rarity_to_color(rarity))
        if "icon" in choice:
            data.set_thumbnail(url=choice["icon"])
        data.add_field(name="Buy price", value=buyprice, inline=False)
        data.add_field(name="Sell price", value=sellprice, inline=False)
        data.set_footer(text=choice["chat_link"])
        try:
            await ctx.send(embed=data)
        except discord.Forbidden:
            await ctx.send("Issue embedding data into discord")

    @tp.command(name="delivery")
    @commands.cooldown(1, 10, BucketType.user)
    async def tp_delivery(self, ctx):
        """Show your items awaiting in delivery box

        Required permissions: tradingpost
        """
        user = ctx.author
        endpoint = "commerce/delivery/"
        try:
            doc = await self.fetch_key(user, ["tradingpost"])
            results = await self.call_api(endpoint, key=doc["key"])
        except APIError as e:
            return await self.error_handler(ctx, e)
        data = discord.Embed(
            description='Current deliveries',
            colour=await self.get_embed_color(ctx))
        data.set_author(
            name='Delivery overview of {0}'.format(doc["account_name"]))
        data.set_thumbnail(url="https://wiki.guildwars2.com/"
                           "images/thumb/d/df/Black-Lion-Logo.png"
                           "/300px-Black-Lion-Logo.png")
        data.set_footer(text="Black Lion Trading Company")
        coins = results["coins"]
        items = results["items"]
        items = items[:20]  # Get only first 20 entries
        item_quantity = []
        itemlist = []
        if coins == 0:
            gold = "Currently no coins for pickup."
        else:
            gold = self.gold_to_coins(ctx, coins)
        data.add_field(name="Coins", value=gold, inline=False)
        counter = 0
        if len(items) != 0:
            for item in items:
                item_quantity.append(item["count"])
                itemdoc = await self.fetch_item(item["id"])
                itemlist.append(itemdoc)
            for item in itemlist:
                item_name = item["name"]
                # Get quantity of items
                quantity = item_quantity[counter]
                counter += 1
                data.add_field(
                    name=item_name,
                    value="x {0}".format(quantity),
                    inline=False)
        else:
            if coins == 0:
                return await ctx.send("Your delivery box is empty!")
            data.add_field(
                name="No current deliveries.", value="Have fun!", inline=False)
        try:
            await ctx.send(embed=data)
        except discord.HTTPException:
            await ctx.send("Need permission to embed links")

    def gold_to_coins(self, ctx, money):
        gold, remainder = divmod(money, 10000)
        silver, copper = divmod(remainder, 100)
        kwargs = {"fallback": True, "fallback_fmt": " {} "}
        gold = "{}{}".format(gold, self.get_emoji(ctx, "gold",
                                                  **kwargs)) if gold else ""
        silver = "{}{}".format(silver, self.get_emoji(
            ctx, "silver", **kwargs)) if silver else ""
        copper = "{}{}".format(copper, self.get_emoji(
            ctx, "copper", **kwargs)) if copper else ""
        return "".join(filter(None, [gold, silver, copper]))

    def rarity_to_color(self, rarity):
        return int(self.gamedata["items"]["rarity_colors"][rarity], 0)

    @commands.group(case_insensitive=True)
    async def gem(self, ctx):
        """Commands related to gems"""
        if ctx.invoked_subcommand is None:
            await ctx.send_help()

    @gem.command(name="price")
    async def gem_price(self, ctx, quantity: int = 400):
        """Lists current gold/gem exchange prices.

        You can specify a custom amount, defaults to 400
        """
        if quantity <= 1:
            return await ctx.send("Quantity must be higher than 1")
        try:
            gem_price = await self.get_gem_price(quantity)
            coin_price = await self.get_coin_price(quantity)
        except APIError as e:
            return await self.error_handler(ctx, e)
        data = discord.Embed(
            title="Currency exchange", colour=await self.get_embed_color(ctx))
        data.add_field(
            name="{} gems would cost you".format(quantity),
            value=self.gold_to_coins(ctx, gem_price),
            inline=False)
        data.set_thumbnail(url="https://render.guildwars2.com/file/220061640EC"
                           "A41C0577758030357221B4ECCE62C/502065.png")
        data.add_field(
            name="{} gems could buy you".format(quantity),
            value=self.gold_to_coins(ctx, coin_price),
            inline=False)
        try:
            await ctx.send(embed=data)
        except discord.Forbidden:
            await ctx.send("Need permission to embed links")

    async def get_gem_price(self, quantity=400):
        endpoint = "commerce/exchange/coins?quantity=10000000"
        results = await self.call_api(endpoint)
        cost = results['coins_per_gem'] * quantity
        return cost

    async def get_coin_price(self, quantity=400):
        endpoint = "commerce/exchange/gems?quantity={}".format(quantity)
        results = await self.call_api(endpoint)
        return results["quantity"]

    @gem.command(name="track", usage="<gold>")
    async def gem_track(self, ctx, gold: int = 0):
        """Receive a notification when cost of 400 gems drops below given cost

        For example, if you set cost to 100, you will get a notification when
        price of 400 gems drops below 100 gold
        """
        user = ctx.author
        if not gold:
            doc = await self.bot.database.get(user, self)
            current = doc.get("gemtrack")
            if current:
                return await ctx.send(
                    "You'll currently be notified if "
                    "price of 400 gems drops below **{}**".format(
                        current // 10000))
            else:
                return await self.send_cmd_help(ctx)
        if not 0 <= gold <= 500:
            return await ctx.send("Invalid value")
        price = gold * 10000
        try:
            await user.send("You will be notified when price of 400 gems "
                            "drops below {} gold".format(gold))
        except:
            return await ctx.send("Couldn't send a DM to you. Either you have "
                                  "me blocked, or disabled DMs in this "
                                  "server. Aborting.")
        await self.bot.database.set(user, {"gemtrack": price}, self)
        await ctx.send("Successfully set")
