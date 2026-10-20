# How the matching works (explained to a 5-year-old)

Imagine you have a toy car, and you want to know if two other toy shops have **the exact same car**.

## 1. First, we look very closely at your toy

We open the Amazon page and write down everything that makes your toy *your* toy:

- **Who made it**: the brand, like *Samsung* or *Nike*.
- **What it's called**: the model, like *Galaxy S25* or *Court Vision*.
- **Its special number**, if it has one: like a name tag sewn inside. A TV has a model number (`K-55S25BM2`); a shoe or shirt has a style code (`IH1476`).
- **The thing that matters for its kind**:
  - a phone: how much it can remember (**RAM**) and how much it can hold (**storage**)
  - a TV: how big the screen is
  - shoes and t-shirts: what **colour** they are

We also check what *kind* of toy it is, from the signpost Amazon puts on its shelf ("Smartphones", "Sneakers", "Polos"). If it's anything else (a sandal, a phone cover, a TV stand, a formal shirt), we say we only know those four kinds of toys.

## 2. Then we go to the other shops and ask "do you have this?"

Phones and TVs: we ask **Flipkart** and **Croma**. Shoes and t-shirts: we ask **Flipkart** and **Myntra**.

Each shop shows us a pile of things that *look* a bit like our toy.

## 3. We play "spot the difference" with every toy in the pile

For each one, we check our list, one item at a time:

| We ask | Same toy? |
|---|---|
| Same maker? | Samsung ≠ Sony → not the same |
| Same name? | "iPhone 15" ≠ "iPhone 15 **Plus**" → not the same |
| Same size / memory / colour? | 128 GB ≠ 256 GB → not the same |
| Is it even the right kind of thing? | a phone *cover* is not a phone; a sandal is not a sneaker |

**Every** answer has to be "yes". One "no" and that toy goes back in the pile.

A few tricks so we don't get fooled:

- **Little words change everything.** "Pro", "Plus", "Ultra" and numbers like "15" or "S25" must match exactly. "FX Pro" is not "X Pro", and a kids' shoe is not the grown-up one.
- **Some words are just shop talk.** "Stylish", "comfortable", "5G", "with Alexa", "4K **Ultra** HD". We didn't guess these: we read about 55,000 real product titles, and a word that dozens of *different* brands all use describes a kind of toy, not a particular one.
- **Shops spell colours differently.** "Jet Black" is black; "Midnight Navy" is navy; "Aubergine" is purple (we know about 950 colour names); and Nike's "Lt Orewood Brn" is light brown.

## 4. The special number is the best clue

Toy names can be vague. A shop might call the official India cricket jersey just "Blue Printed T-Shirt". So when Amazon gives a special number, we **open the shop's page for that toy and read its number**:

- **Same number** → it's definitely the same toy, even if the shop gave it a boring name.
- **Different number** → it's a different toy, even if it looks the same ("Stan Smith `FX5501`" is not "Stan Smith `FX5502`": that's another colour).
- **A tiny tail is OK; a new number isn't.** `43NU870` and `43NU870BPLA` are the same TV (the tail just says which country). `K-55S25B` and `K-55S25BM2` are different TVs: "M2" is the newer one.

We always read the number of any toy *before* we show it to you.

## 5. Finally, we check if you can actually buy it

- **Flipkart** tells us on its page ("in stock" or "sold out").
- **Croma** tells us city by city, so we ask for Mumbai, Delhi and Bengaluru. If any of them can deliver it, it's in stock.
- **Myntra** tells us which sizes are left. No sizes left means out of stock.

If the exact toy is sold out, we say **"out of stock"**. We never swap in a different toy that happens to be in stock.

## 6. And we tell you what we found

| | What it means |
|---|---|
| ● **In stock** | Found the same toy, and you can buy it. Here's the link. |
| ◐ **Out of stock** | Found the same toy, but you can't buy it right now. Here's the link anyway. |
| ○ **Listed · stock unconfirmed** | Found the same toy, but the shop didn't tell us if it's in stock. Here's the link to check. |
| ○ **Not listed** | This shop doesn't have this toy. (We still show the closest ones we saw and *why* they weren't the same.) |

If a shop doesn't answer the phone at all, we say **"Couldn't check"** instead of pretending it doesn't have the toy.

## How do we know it works?

We didn't just try a few toys. We looked up **about 760 real Amazon products** (phones, TVs, sneakers, t-shirts, polos, jerseys from over 100 brands) and used the special numbers on both sides as the answer key:

- Whenever there was a special number to check, our answer was **right every time** (about 190 checks), including on 170 products we had never looked at while building it.
- Phones checked by eye: right every time.
- The weak spot: **plain clothes with no special number and a one-word name** (like "Everyday Basic" vs "Elevated Basics"). There, about 1 in 7 can be a lookalike, so the app marks those as **"medium confidence"**.

## The one rule behind all of it

**It's better to say "I couldn't find it" than to send you to the wrong toy.** So a match has to pass every check that matters for its kind (colour only counts as a preference for phones and TVs), a special number beats a vague name, and if a shop won't tell us whether it's in stock we say "stock unconfirmed" instead of guessing. The app shows you the checklist, so you never have to take our word for it.
