# 🔑 Beginner API Key Setup Guide
*Explained like you're 10 years old!*

## What are API Keys?
Think of API keys like special passwords that let our program talk to other websites (like News, Reddit, etc.) to get information. Without these passwords, our program can't get news or stock data.

## Step 1: News API (Gets news articles)

### What is it?
News API gives us news articles about stocks. Free = 100 articles per day.

### How to get it:
1. Click this link: https://newsapi.org/register
2. You'll see a form like this:
   ```
   First Name: (type your name)
   Last Name: (type your last name)
   Email: (type your email)
   Password: (make up a password)
   ```
3. Click "Create Account"
4. Check your email (the email you typed in step 2)
5. Click the link in the email to verify your account
6. After clicking, you'll see a page with your API Key
7. **Copy that key** (select it and press Ctrl+C)

### Where to paste it:
1. Open folder: `C:\Users\Sham\Desktop\Projects\NLP SENTIMENT ANALYSIS\SmartTrader\`
2. Find the file named `.env` (it might look invisible, but it's there)
3. Double-click it → Choose "Notepad" to open
4. Find this line: `NEWS_API_KEY=`
5. Paste your key after the `=` sign, like: `NEWS_API_KEY=abc123def456...`
6. Click "File" → "Save" (or press Ctrl+S)
7. Close Notepad

---

## Step 2: Reddit API (Gets Reddit posts)

### What is it?
Reddit is where people talk about stocks. This lets us listen to those conversations. Free!

### How to get it:
1. Click: https://www.reddit.com/prefs/apps
2. If you don't have Reddit account, click "Sign Up" first (it's free)
   - Just type username, password, email
   - Click "Sign Up"
3. After login, you'll see a page that says "Developed Applications"
4. Click the button that says "create another app..." or "are you a developer? create an app..."
5. Fill in the form:
   ```
   name: SmartTrader (type this)
   App type: click the circle next to "script"
   description: (can leave empty)
   about url: (can leave empty)
   redirect uri: http://localhost:8080 (type this exactly)
   ```
6. Click "create app"
7. You'll see a box with your new app. It has:
   - **CLIENT ID**: Under "personal use script" - copy this (looks like: `abC123xyz`)
   - **CLIENT SECRET**: Next to "secret" - copy this (looks like: `123abc456def...`)

### Where to paste them:
1. Open `.env` file again (same as before)
2. Find these lines:
   ```
   REDDIT_CLIENT_ID=
   REDDIT_CLIENT_SECRET=
   ```
3. Paste CLIENT ID after `REDDIT_CLIENT_ID=`
4. Paste CLIENT SECRET after `REDDIT_CLIENT_SECRET=`
5. Save and close

---

## Step 3: Finnhub API (Gets stock expert opinions)

### What is it?
Finnhub gives us what experts say about stocks. Free = 60 requests per minute.

### How to get it:
1. Click: https://finnhub.io/register
2. Fill form:
   ```
   Email: (your email)
   Password: (make a password)
   ```
3. Click "Create Account"
4. Verify your email (check inbox, click link)
5. After login, you'll see dashboard
6. Look for "API Keys" or "Dashboard" → copy the key (looks like: `c1abc23d.xyz456...`)

### Where to paste it:
1. Open `.env` file
2. Find: `FINNHUB_API_KEY=`
3. Paste your key after `=`
4. Save and close

---

## Step 4: Shoonya API (THE FREE WAY to trade in India)

### What is it?
Shoonya is a website that lets you buy/sell stocks in India for **FREE**. No monthly fees, no brokerage. This is our recommended way!

### How to get it:
1. Sign up here: https://prism.finvasia.com/ (requires Aadhar/PAN)
2. Once account is open, go to **API Management**.
3. Create a new API Key.
4. You will get: **User ID**, **Password**, **TOTP Key**, **Vendor Code**, and **API Key**.

### Where to paste:
Open `.env` file and paste them like this:
```env
SHOONYA_USER_ID=your_id
SHOONYA_PASSWORD=your_password
SHOONYA_TOTP_KEY=your_totp_key
SHOONYA_VENDOR_CODE=your_vendor_code_VC
SHOONYA_API_KEY=your_api_key
```

---

## Step 5: Zerodha API (Alternative auto-trading)

1. Open the `.env` file (with Notepad)
2. It should look like this (with your actual keys):
   ```
   NEWS_API_KEY=abc123... (your actual key)
   REDDIT_CLIENT_ID=abC123...
   REDDIT_CLIENT_SECRET=xyz789...
   FINNHUB_API_KEY=c1abc23...
   ```

3. Save and close

4. Test it! Open your command prompt (black window) and type:
   ```bash
   cd "C:\Users\Sham\Desktop\Projects\NLP SENTIMENT ANALYSIS\SmartTrader"
   venv\Scripts\activate
   python main.py --mode screen
   ```

5. If you see a list of stocks, **IT WORKED!** 🎉

---

## Need Help? Common Problems:

### "I can't find the .env file!"
- Open the folder in File Explorer
- Click "View" at top
- Check the box that says "Hidden items"
- Now you'll see `.env` file

### "The link doesn't work!"
- Make sure you're connected to internet
- Try copying the link and pasting in your browser

### "It says 'invalid API key'!"
- You probably copied it wrong
- Go back to the website, find your API key
- Copy it again (make sure no extra spaces!)
- Paste in `.env` file, save

### "I don't get the email verification!"
- Check your Spam/Junk folder
- Wait 5 minutes
- Try registering again with correct email

---

## You Did It! 🎊

Now your SmartTrader can:
- ✅ Read news about stocks (News API)
- ✅ Listen to Reddit talks (Reddit API)
- ✅ See expert opinions (Finnhub)
- ✅ (New!) Trade for FREE with Shoonya (Zero Brokerage)
- ✅ (Soon) Trade automatically (Zerodha)

**Next step**: Run `python main.py --mode screen` to find winning stocks!
