# -*- coding: utf-8 -*-
"""
Exports all the users 'on' a provided wiki to an xml file.

We consider a person a 'user of' a wiki if they have made some sort of edit
there.

This is really just a minimal export.

enc_password is a base64 encoded SHA has of their plain text password, like so:

import base64
def hash(cleartext):
    return base64.encodestring(sha.new(cleartext.encode('utf-8')).digest()
                              ).rstrip()

Format of the XML file is:

<sycamore version="0.1d">
<users>
    <user
        name="<their username>"
        email="<email address>"
        enc_password="<encoded password, see description above>"
        disabled="<1 if account is disabled>"
    />
</users>
</sycamore>
"""

EXPORT_ENC_PASSWORD = False

import sys
import time
import os
import xml.dom.minidom
from xml.dom.minidom import getDOMImplementation

import __init__ # woo hackmagic
__directory__ = os.path.dirname(__file__)
share_directory = os.path.abspath(
    os.path.join(__directory__, '..', 'share'))
sys.path.extend([share_directory])

from Sycamore import config
from Sycamore import wikiutil
from Sycamore import request
from Sycamore import user

xml = getDOMImplementation()
dummy_name = "attrs"

def generate_attributes(dict):
    """
    Given a dictionary we create a string of XML-y attributes.
    """
    doc = xml.createDocument(None, dummy_name, None)
    root = doc.documentElement
    for key, value in dict.iteritems():
        if type(value) is str:
            value = value.decode(config.charset)
        elif value is None:
            value = ''
        elif type(value) is not unicode:
            value = str(value).decode(config.charset)
        root.setAttribute(key, value)

    return root.toxml()[len(dummy_name)+2:-2].encode(config.charset)


def users(request, f):
    request.cursor.execute(
        """SELECT users.propercased_name, users.email, enc_password,
                  users.disabled
           FROM users, userWikiInfo
           WHERE users.name !='' and (userWikiInfo.edit_count > 0 or userWikiInfo.file_count > 0) and
                 users.name=userWikiInfo.user_name and
                 userWikiInfo.wiki_id=%(wiki_id)s""",
        {'wiki_id':request.config.wiki_id})
    for name, email, enc_password, disabled in request.cursor.fetchall():
        if not EXPORT_ENC_PASSWORD:
	    enc_password = ''
        d = {
            'name': name,
            'email': email,
            'enc_password': enc_password,
            'disabled': disabled,
        }
        f.write('<user %s/>\n' % generate_attributes(d))


def export(request, wiki_name=None):
    """
    We do this in chunks because loading an entire wiki into memory
    is kinda a bad idea.
    """
    if not wiki_name:
        # TODO: full export
        return
    f = open('%s.%s.users.xml' % (wiki_name, time.time()), 'w')

    xml_header = ('<?xml version="1.0" encoding="UTF-8"?>\n'
                  '<sycamore>\n'
                  '<users>\n')
    xml_footer = '</users>\n</sycamore>'

    f.write(xml_header)
    users(request, f)
    f.write(xml_footer)

    f.close()


if __name__ == '__main__':
    command_line = True

    sys.stdout.write("Enter the wiki shortname: ")
    wiki_name = raw_input().strip().lower()

    req = request.RequestDummy(wiki_name=wiki_name)

    export(req, wiki_name=wiki_name)
    req.db_disconnect()
