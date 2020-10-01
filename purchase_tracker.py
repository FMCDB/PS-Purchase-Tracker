# -*- coding: utf-8 -*-
from __future__ import print_function
import pickle
import os.path
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
import base64
from apiclient import errors
from bs4 import BeautifulSoup
from flask import Flask, render_template
import sqlite3
import unicodedata

# If modifying these scopes, delete the file token.pickle.
SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']

connection = sqlite3.connect('database.db', check_same_thread=False)

with open('schema.sql') as f:
    connection.executescript(f.read())

def get_db_connection():
	conn = sqlite3.connect('database.db')
	conn.row_factory = sqlite3.Row
	return conn

app = Flask(__name__)

@app.route('/')
def index():
    return render_template('base.html', purchases=start())

def start():
    
    creds = None
    # The file token.pickle stores the user's access and refresh tokens, and is
    # created automatically when the authorization flow completes for the first
    # time.
    if os.path.exists('token.pickle'):
        with open('token.pickle', 'rb') as token:
            creds = pickle.load(token)
    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                'credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        # Save the credentials for the next run
        with open('token.pickle', 'wb') as token:
            pickle.dump(creds, token)
    
    service = build('gmail', 'v1', credentials=creds)
    user_id = "me"
    query = 'from:Playstation subject:(\'Thank You For Your Purchase\')'
    
    conn = get_db_connection()
    purchases = conn.execute('SELECT id FROM purchases').fetchall()
    purchase_ids = [ sub['id'] for sub in purchases ] 
    
    check_for_new_purchases(service, user_id, query, purchase_ids)
    connection.commit()
    
    new_purchases = conn.execute('SELECT * FROM purchases').fetchall()
    
    return new_purchases
    

def GetMessage(service, user_id, msg_id):
  """Get a Message with given ID.

  Args:
    service: Authorized Gmail API service instance.
    user_id: User's email address. The special value "me"
    can be used to indicate the authenticated user.
    msg_id: The ID of the Message required.

  Returns:
    A Message.
  """
  try:
    msg = service.users().messages().get(userId=user_id, id=msg_id, format='full').execute()
    msg_body = msg.get("payload").get("body").get("data")
    if msg_body:
        return base64.urlsafe_b64decode(msg_body.encode("ASCII")).decode("utf-8")
    return msg.get("snippet") 
  except errors.HttpError as error:
    print('An error occurred: %s' % error)
    
        
        
def check_for_new_purchases(service, user_id, query, purchase_ids):
    
    messages = []
    
    print('\n\nSearching for new purchses...\n')
    
    # get first page of results corresponding to query, add to messages list
    response = service.users().messages().list(userId=user_id,q=query).execute()
    
    # if the message isn't in the database
    if 'messages' in response and response['messages'][0]['id'] not in purchase_ids:
        
        print('New purchases have been made:\n')
        response, messages = update_messages(response, messages, purchase_ids)
    
        # Keep adding the next page of results (not in database) to messages 
        while 'nextPageToken' in response:
            page_token = response['nextPageToken']
            response = service.users().messages().list(userId=user_id, q=query,pageToken=page_token).execute()
            response, messages = update_messages(response, messages, purchase_ids)
          
        update_purchases(service, user_id, messages)
        
    else:
        print('No new purchases have been made')
        
    return messages    
      

def update_messages(response, messages, purchase_ids): 
    for message in response['messages']:
        if message['id'] not in purchase_ids:
            messages.append(message['id'])
        else:
            response = {} #To prevent while loop
            return response, messages
    return response, messages



def update_purchases(service, user_id, messages):
    
    # Extracts relevant data from emails and inserts this into database
    
    cur = connection.cursor()
    
    for msg_id in messages:
        
        html_doc = GetMessage(service, user_id, msg_id)
        
        #HTML PARSING:
        # Title: 1st use of <strong>
        # Price: First use of euro sign ( € )
        # Date: date in email
        
        invalid = ['Fund Sources Used (Total)', 
                   'Next payment date:', 
                   'To turn off automatic funding from:',
                   'At the time of making your purchase, you asked us to provide you with immediate access to your purchase and confirmed your understanding that this means:']
        
        soup = BeautifulSoup(html_doc, 'html.parser')
        strong_tags = soup.find_all('strong')
        b_tags = soup.find_all('b')
        a_tags = soup.find_all('a')
        td_tags_bottom = soup.findAll('td', {'valign' : 'bottom'}, {'align' : 'left'})
        td_tags_middle = soup.findAll('td', {'valign' : 'middle'}, {'align' : 'left'})
        
        if len(strong_tags) > 0 and (strong_tags[0].get_text().strip() not in invalid):    
             title_container = strong_tags[0]
        elif len(b_tags) > 0 and (b_tags[0].get_text().strip() not in invalid):
            title_container = b_tags[0]
        elif len(td_tags_bottom) > 0:
            title_container = td_tags_bottom[0]
        else:
            title_container = a_tags[2]
            
        #Title
        title = title_container.get_text().strip()
        if 'Current Wallet Amount' in title:
            title_container = td_tags_middle[4]
            if len(title_container.get_text().strip()) == 0:   
                title_container = td_tags_middle[6]
            title = title_container.get_text().strip()
        if '\r' in title:
            title = title[:title.index('\r')-2]
            
        #Type
        if title[-1] == ')':
            start = title.rfind('(')+1
            end = title.rfind(')')
            purchase_type = title[start:end]
            title = title[:title.find(purchase_type)-2]
        
        text = soup.get_text()
        
        #Price
        start = text.find('{}'.format(unicodedata.lookup("EURO SIGN")))
        end = start + 6
        price = text[start:end].strip()
        
        #Date
        if ' AM' in text or ' PM' in text:
            period = ' AM' if ' AM' in text else ' PM'
            start = text.find(period) - 16
            end = text.find(period) + 3
        else:
            heading = 'Date and time of purchase: '
            start = text.find(heading) + len(heading)
            end = start + 10
        date = text[start:end].strip()
        
        if '@' in date:
            date = text[start-2:end].strip()
            date = date.replace('@','').replace(' ','',1)
            
        purchase_dict = {
            'Title': title,
            'Type': purchase_type,
            'Price': price,
            'Date': date
        }
        
        print(purchase_dict)
            
        cur.execute("INSERT INTO purchases (id, title, type, price, date) VALUES (?, ?, ?, ?, ?)",
            (msg_id, title, purchase_type, price, date))

        
      
if __name__ == '__main__':
    start()
