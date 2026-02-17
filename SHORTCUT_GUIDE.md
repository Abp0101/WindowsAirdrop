# MyDrop - iOS Shortcut Guide

You don't need a special app on your iPhone! We'll use a **Run Script** or standard **iOS Shortcut** to send files directly to your PC.

## 1. Create the Shortcut

1. Open the **Shortcuts** app on your iPhone.
2. Tap **+** to create a new shortcut.
3. Name it **"MyDrop to PC"**.
4. Enable **"Show in Share Sheet"**:
   - Tap the (i) icon at the bottom.
   - Toggle **Show in Share Sheet** ON.
   - Set "Receive" to **Images, Media, and Files**.

## 2. Add the Actions

Add these actions in order:

### Action 1: `Get Contents of URL`
- **URL**: `http://YOUR_PC_IP:53317/ios-upload`
  *(Replace `YOUR_PC_IP` with the IP shown in the Windows app, e.g., `192.168.1.5`)*
- **Method**: `POST`
- **Headers**:
  - `X-Pin`: `1234` (or whatever PIN you want to use)
  - `X-Filename`: `Shortcut Input.Name` (Tap "Shortcut Input", select "Name")
- **Request Body**: `File`
  - Set content to **Shortcut Input**.

### Action 2: `Get value for key` (Optional but verifying)
- **Key**: `success`
- **Dictionary**: `Contents of URL` (output from step 1)

### Action 3: `Show Alert`
- **Title**: `Sent!`
- **Message**: `File sent to PC.`

## 3. How to Use
1. Open **Photos** or **Files** on your iPhone.
2. Tap the **Share** button (box with arrow).
3. Scroll down and tap **"MyDrop to PC"**.
4. You'll see a small progress circle, then "Sent!".
5. Check your PC's `Downloads/MyDrop` folder!
