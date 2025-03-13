from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from pymongo import MongoClient
from flask_bcrypt import Bcrypt
from flask_socketio import SocketIO, emit, join_room, leave_room
import os
import random
import smtplib
from email.mime.text import MIMEText
from bson.objectid import ObjectId
from datetime import datetime

app = Flask(__name__)
app.secret_key = os.urandom(24)  # Secret key for session management
socketio = SocketIO(app)

# MongoDB connection
client = MongoClient('mongodb+srv://studyhive2027:jN3eHrZ25j901yOJ@cluster0.utukd.mongodb.net/')
db = client["userDB"]
users_collection = db["users"]
todos_collection = db["todos"]
expenses_collection = db["expenses"]
messages_collection = db["messages"]
conversations_collection = db["conversations"]

# Bcrypt for password hashing
bcrypt = Bcrypt(app)

# Store OTPs temporarily (in-memory storage)
otp_storage = {}

# Home route
@app.route('/')
def home():
    if 'username' in session:
        username = session['username']
        return render_template('home.html', username=username)
    return redirect(url_for('login'))

# Signup route
@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        email = request.form['email']
        username = request.form['username']
        password = request.form['password']
        confirm_password = request.form['confirm_password']  # Added confirm password field

        # Check if passwords match
        if password != confirm_password:
            flash("Passwords do not match!", "error")
            return redirect(url_for('signup'))

        # Check if user already exists
        if users_collection.find_one({"username": username}):
            flash("Username already exists!", "error")
            return redirect(url_for('signup'))
        if users_collection.find_one({'email': email}):
            flash("Email already exists!", "error")
            return redirect(url_for('signup'))

        # Hash password
        hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')

        # Insert user into MongoDB
        users_collection.insert_one({
            'email': email,
            "username": username,
            "password": hashed_password
        })

        flash("Account created successfully! Please login.", "success")
        return redirect(url_for('login'))

    return render_template('signup.html')

# Login route
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username_or_email = request.form['username_or_email']  # Get the input value
        password = request.form['password']

        # Check if the input is an email or username
        if '@' in username_or_email:
            # Search by email
            user = users_collection.find_one({'email': username_or_email})
        else:
            # Search by username
            user = users_collection.find_one({'username': username_or_email})

        # Verify user and password
        if user and bcrypt.check_password_hash(user['password'], password):
            session['username'] = user['username']  # Store username in session
            return redirect(url_for('home'))
        else:
            flash("Invalid username/email or password!", "error")

    return render_template('login.html')

# Logout route
@app.route('/logout')
def logout():
    session.pop('username', None)
    flash("You have been logged out.", "success")  # Optional: Show a logout message
    return redirect(url_for('login'))

# Forgot password route
@app.route("/forgotpassword", methods=['GET', 'POST'])
def forgotpassword():
    if request.method == 'POST':
        email = request.form['email']
        # Add logic to handle password reset (e.g., send an email)
        flash("Password reset link has been sent to your email.", "success")
        return redirect(url_for('login'))
    return render_template('forgotpassword.html')

# Store OTPs separately for signup and forgot password
signup_otp_storage = {}  
forgot_password_otp_storage = {}  

# Function to send OTP via email (Updated Subject for Signup)
def send_otp_email(email, otp, purpose):
    sender_email = "studyhive2027@gmail.com"
    sender_password = "prfi rqqg qyoo dyqf"

    subject = "Account Signup OTP" if purpose == "signup" else "Password Reset OTP"
    message = MIMEText(f"Your OTP for {purpose} is: {otp}")
    message['Subject'] = subject
    message['From'] = sender_email
    message['To'] = email

    try:
        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.starttls()
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, [email], message.as_string())
        return True
    except Exception as e:
        print(f"Error sending OTP: {e}")
        return False

@app.route('/send_otp', methods=['POST'])
def send_otp():
    data = request.json
    email = data['email']

    # Check if the email exists in the database
    if not users_collection.find_one({'email': email}):
        return jsonify({'success': False, 'message': 'Email not found.'})

    # Generate a 6-digit OTP
    otp = str(random.randint(100000, 999999))
    forgot_password_otp_storage[email] = otp  # Store OTP for forgot password

    print(f"🔹 OTP for {email} (Forgot Password): {otp}")  # Debugging

    if send_otp_email(email, otp, "forgot password"):
        return jsonify({'success': True, 'otp': otp})  # Send OTP for debugging
    else:
        return jsonify({'success': False, 'message': 'Failed to send OTP.'})

# Route to reset password
@app.route('/reset_password', methods=['POST'])
def reset_password():
    data = request.json
    email = data['email']
    new_password = data['newPassword']
    entered_otp = data['otp']

    print(f"🔍 Verifying Forgot Password OTP for {email}. Expected: {forgot_password_otp_storage.get(email)}, Received: {entered_otp}")

    # Check if OTP matches
    if email not in forgot_password_otp_storage or forgot_password_otp_storage[email] != entered_otp:
        return jsonify({'success': False, 'message': 'Invalid OTP. Please try again.'})

    # Hash the new password
    hashed_password = bcrypt.generate_password_hash(new_password).decode('utf-8')

    # Update the user's password in the database
    users_collection.update_one({'email': email}, {'$set': {'password': hashed_password}})

    # Remove OTP after successful verification
    del forgot_password_otp_storage[email]

    return jsonify({'success': True})

# Route to add a new To-Do item
@app.route('/add_todo', methods=['POST'])
def add_todo():
    if 'username' not in session:
        return jsonify({'success': False, 'message': 'User not logged in.'})

    username = session['username']
    task = request.json.get('task')
    task_date = request.json.get('task_date')
    
    # If task_date is not provided, use today's date
    if not task_date:
        from datetime import date
        task_date = date.today().strftime('%Y-%m-%d')

    if not task:
        return jsonify({'success': False, 'message': 'Task cannot be empty.'})

    # Insert the new task into the database
    todos_collection.insert_one({
        'username': username,
        'task': task,
        'task_date': task_date,
        'completed': False
    })

    return jsonify({'success': True})

# Route to get all To-Do items for the logged-in user
@app.route('/get_todos', methods=['GET'])
def get_todos():
    if 'username' not in session:
        return jsonify({'success': False, 'message': 'User not logged in.'})

    username = session['username']
    todos = list(todos_collection.find({'username': username}))

    # Convert ObjectId to string for JSON serialization
    for todo in todos:
        todo['_id'] = str(todo['_id'])

    return jsonify({'success': True, 'todos': todos})

# Route to mark a To-Do item as completed
@app.route('/complete_todo', methods=['POST'])
def complete_todo():
    if 'username' not in session:
        return jsonify({'success': False, 'message': 'User not logged in.'})

    todo_id = request.json.get('todo_id')
    if not todo_id:
        return jsonify({'success': False, 'message': 'Todo ID is required.'})

    # Update the task as completed
    todos_collection.update_one({'_id': ObjectId(todo_id)}, {'$set': {'completed': True}})

    return jsonify({'success': True})

# Route to delete a To-Do item
@app.route('/delete_todo', methods=['POST'])
def delete_todo():
    if 'username' not in session:
        return jsonify({'success': False, 'message': 'User not logged in.'})

    todo_id = request.json.get('todo_id')
    if not todo_id:
        return jsonify({'success': False, 'message': 'Todo ID is required.'})

    # Delete the task
    todos_collection.delete_one({'_id': ObjectId(todo_id)})

    return jsonify({'success': True})

# Route to add a new expense
@app.route('/add_expense', methods=['POST'])
def add_expense():
    if 'username' not in session:
        return jsonify({'success': False, 'message': 'User not logged in.'})

    username = session['username']
    expense_name = request.json.get('expense_name')
    expense_amount = request.json.get('expense_amount')

    if not expense_name or not expense_amount:
        return jsonify({'success': False, 'message': 'Expense name and amount are required.'})

    # Insert the new expense into the database
    expenses_collection.insert_one({
        'username': username,
        'expense_name': expense_name,
        'expense_amount': float(expense_amount)
    })

    return jsonify({'success': True})

# Route to get all expenses for the logged-in user
@app.route('/get_expenses', methods=['GET'])
def get_expenses():
    if 'username' not in session:
        return jsonify({'success': False, 'message': 'User not logged in.'})

    username = session['username']
    expenses = list(expenses_collection.find({'username': username}))

    # Convert ObjectId to string for JSON serialization
    for expense in expenses:
        expense['_id'] = str(expense['_id'])

    return jsonify({'success': True, 'expenses': expenses})

# Route to delete an expense
@app.route('/delete_expense', methods=['POST'])
def delete_expense():
    if 'username' not in session:
        return jsonify({'success': False, 'message': 'User not logged in.'})

    expense_id = request.json.get('expense_id')
    if not expense_id:
        return jsonify({'success': False, 'message': 'Expense ID is required.'})

    # Delete the expense
    expenses_collection.delete_one({'_id': ObjectId(expense_id)})

    return jsonify({'success': True})

# Route to set or update total balance
@app.route('/set_balance', methods=['POST'])
def set_balance():
    if 'username' not in session:
        return jsonify({'success': False, 'message': 'User not logged in.'})

    username = session['username']
    new_balance = request.json.get('balance')

    if new_balance is None:
        return jsonify({'success': False, 'message': 'Balance amount is required.'})

    # Update or insert the balance in the database
    db.balances.update_one({'username': username}, {'$set': {'balance': float(new_balance)}}, upsert=True)

    return jsonify({'success': True, 'message': 'Balance updated successfully.'})

# Route to get the total balance
@app.route('/get_balance', methods=['GET'])
def get_balance():
    if 'username' not in session:
        return jsonify({'success': False, 'message': 'User not logged in.'})

    username = session['username']
    balance_data = db.balances.find_one({'username': username})

    balance = balance_data['balance'] if balance_data else 0  # Default to 0 if not set
    return jsonify({'success': True, 'balance': balance})

@app.route('/update_balance', methods=['POST'])
def update_balance():
    if 'username' not in session:
        return jsonify({'success': False, 'message': 'User not logged in.'})

    username = session['username']
    expense_name = request.json.get('expense_name')
    expense_amount = request.json.get('expense_amount')

    if not expense_name or expense_amount is None:
        return jsonify({'success': False, 'message': 'Expense name and amount are required.'})

    # Fetch current balance
    balance_data = db.balances.find_one({'username': username})
    current_balance = balance_data['balance'] if balance_data else 0

    # Ensure user cannot overspend
    if expense_amount > current_balance:
        return jsonify({'success': False, 'message': 'Insufficient balance.'})

    # Deduct expense from balance
    new_balance = current_balance - expense_amount

    # Update database
    db.expenses.insert_one({'username': username, 'expense_name': expense_name, 'expense_amount': float(expense_amount)})
    db.balances.update_one({'username': username}, {'$set': {'balance': new_balance}})

    return jsonify({'success': True, 'new_balance': new_balance})

# Route to delete an expense and restore balance
@app.route('/reset_balance', methods=['POST'])
def reset_balance():
    if 'username' not in session:
        return jsonify({'success': False, 'message': 'User not logged in.'})

    expense_id = request.json.get('expense_id')

    if not expense_id:
        return jsonify({'success': False, 'message': 'Expense ID is required.'})

    # Find the expense amount before deleting
    expense = db.expenses.find_one({'_id': ObjectId(expense_id)})

    if not expense:
        return jsonify({'success': False, 'message': 'Expense not found.'})

    expense_amount = expense['expense_amount']

    # Restore the balance
    balance_data = db.balances.find_one({'username': session['username']})
    current_balance = balance_data['balance'] if balance_data else 0
    new_balance = current_balance + expense_amount

    # Delete expense and update balance
    db.expenses.delete_one({'_id': ObjectId(expense_id)})
    db.balances.update_one({'username': session['username']}, {'$set': {'balance': new_balance}})

    return jsonify({'success': True, 'new_balance': new_balance})

@app.route('/send_signup_otp', methods=['POST'])
def send_signup_otp():
    data = request.json
    email = data['email']

    # Check if email is already registered
    if users_collection.find_one({'email': email}):
        return jsonify({'success': False, 'message': 'Email already registered.'})

    # Generate and store OTP
    otp = str(random.randint(100000, 999999))
    signup_otp_storage[email] = otp  # Store OTP

    print(f"✅ OTP for {email}: {otp}")  # Debugging

    if send_otp_email(email, otp, "signup"):
        return jsonify({'success': True, 'otp': otp})  # Send OTP for debugging
    else:
        return jsonify({'success': False, 'message': 'Failed to send OTP.'})

@app.route('/verify_signup_otp', methods=['POST'])
def verify_signup_otp():
    data = request.json
    email = data['email']
    username = data['username']
    password = data['password']
    otp = data['otp']

    print(f"🔍 Verifying OTP for {email}. Expected: {signup_otp_storage.get(email, 'N/A')}, Received: {otp}")

    # Check if OTP matches
    if email not in signup_otp_storage or signup_otp_storage[email] != otp:
        return jsonify({'success': False, 'message': 'Invalid OTP. Please try again.'})

    # Hash the password
    hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')

    # Store user in the database
    users_collection.insert_one({
        'email': email,
        'username': username,
        'password': hashed_password
    })

    # Remove OTP after successful verification
    del signup_otp_storage[email]

    return jsonify({'success': True})

@app.route('/pythonhub')
def pythonhub():
    return render_template("python.html")

@app.route('/js')
def js():
    return render_template("javascript.html")

@app.route('/web-dev')
def webdev():
    return render_template("web-development.html")

@app.route('/java')
def java():
    return render_template("java.html")

@app.route('/c')
def c():
    return render_template("c.html")

@app.route('/cyber')
def cyber():
    return render_template("cyber.html")

@app.route('/todo')
def todo_page():
    return render_template('todo5.html')

# Messaging routes
@app.route('/messages')
def messages():
    if 'username' not in session:
        return redirect(url_for('login'))
    return render_template('messages.html', username=session['username'])

@app.route('/api/conversations', methods=['GET'])
def get_conversations():
    if 'username' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    
    username = session['username']
    conversations = conversations_collection.find({
        'participants': username
    }).sort('last_message_time', -1)
    
    result = []
    for conv in conversations:
        other_user = next(p for p in conv['participants'] if p != username)
        result.append({
            'id': str(conv['_id']),
            'other_user': other_user,
            'last_message': conv.get('last_message', ''),
            'last_message_time': conv.get('last_message_time', ''),
            'unread_count': conv.get('unread_count', {}).get(username, 0)
        })
    
    return jsonify(result)

@app.route('/api/messages/<conversation_id>', methods=['GET'])
def get_messages(conversation_id):
    if 'username' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    
    messages = messages_collection.find({
        'conversation_id': ObjectId(conversation_id)
    }).sort('timestamp', 1)
    
    result = []
    for msg in messages:
        result.append({
            'id': str(msg['_id']),
            'sender': msg['sender'],
            'content': msg['content'],
            'timestamp': msg['timestamp'].isoformat()
        })
    
    return jsonify(result)

@app.route('/api/conversations', methods=['POST'])
def create_conversation():
    if 'username' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    
    data = request.json
    other_user = data.get('username')
    
    if not users_collection.find_one({'username': other_user}):
        return jsonify({'error': 'User not found'}), 404
    
    existing_conv = conversations_collection.find_one({
        'participants': {'$all': [session['username'], other_user]}
    })
    
    if existing_conv:
        return jsonify({'id': str(existing_conv['_id'])})
    
    new_conv = conversations_collection.insert_one({
        'participants': [session['username'], other_user],
        'created_at': datetime.utcnow(),
        'last_message_time': datetime.utcnow(),
        'unread_count': {session['username']: 0, other_user: 0}
    })
    
    return jsonify({'id': str(new_conv.inserted_id)})

# Route to search for users
@app.route('/api/search_users', methods=['GET'])
def search_users():
    if 'username' not in session:
        return jsonify({'success': False, 'message': 'User not logged in.'})
    
    current_username = session['username']
    query = request.args.get('query', '')
    
    if not query:
        return jsonify({'success': False, 'message': 'Search query is required.'})
    
    # Search for users whose username contains the query (case-insensitive)
    # Exclude the current user from results
    users = list(users_collection.find({
        '$and': [
            {'username': {'$regex': query, '$options': 'i'}},
            {'username': {'$ne': current_username}}
        ]
    }, {'_id': 0, 'username': 1}))
    
    return jsonify({'success': True, 'users': users})

# WebSocket events
@socketio.on('connect')
def handle_connect():
    if 'username' not in session:
        return False
    join_room(session['username'])

@socketio.on('send_message')
def handle_message(data):
    if 'username' not in session:
        return
    
    conversation_id = ObjectId(data['conversation_id'])
    content = data['content']
    sender = session['username']
    timestamp = datetime.utcnow()
    
    # Save message to database
    message = {
        'conversation_id': conversation_id,
        'sender': sender,
        'content': content,
        'timestamp': timestamp
    }
    messages_collection.insert_one(message)
    
    # Update conversation
    conv = conversations_collection.find_one({'_id': conversation_id})
    other_user = next(p for p in conv['participants'] if p != sender)
    
    conversations_collection.update_one(
        {'_id': conversation_id},
        {
            '$set': {
                'last_message': content,
                'last_message_time': timestamp
            },
            '$inc': {f'unread_count.{other_user}': 1}
        }
    )
    
    # Emit to other user
    emit('new_message', {
        'conversation_id': str(conversation_id),
        'sender': sender,
        'content': content,
        'timestamp': timestamp.isoformat()
    }, room=other_user)

@socketio.on('mark_read')
def handle_mark_read(data):
    if 'username' not in session:
        return
    
    conversation_id = ObjectId(data['conversation_id'])
    username = session['username']
    
    conversations_collection.update_one(
        {'_id': conversation_id},
        {'$set': {f'unread_count.{username}': 0}}
    )

if __name__ == '__main__':
    socketio.run(app, debug=True)