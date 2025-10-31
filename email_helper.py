# Email helper for sending family invites using Replit Mail integration
# References: blueprint:replitmail

import os
import requests
import logging

logger = logging.getLogger(__name__)


def get_auth_token():
    """Get authentication token for Replit services"""
    repl_identity = os.environ.get('REPL_IDENTITY')
    web_repl_renewal = os.environ.get('WEB_REPL_RENEWAL')
    
    if repl_identity:
        return f"repl {repl_identity}"
    elif web_repl_renewal:
        return f"depl {web_repl_renewal}"
    else:
        raise Exception("No authentication token found. Please ensure you're running in Replit environment.")


def send_family_invite_email(recipient_email, family_name, invite_code, inviter_name, app_url):
    """
    Send a family invite email using Replit Mail
    
    Args:
        recipient_email: Email address of the person being invited
        family_name: Name of the family (surname)
        invite_code: The 8-character invite code
        inviter_name: Name of the person sending the invite
        app_url: Base URL of the application
    
    Returns:
        dict: Response from the email service
    """
    try:
        auth_token = get_auth_token()
        
        # Create beautiful HTML email
        html_content = f"""
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 30px; text-align: center; border-radius: 8px 8px 0 0; }}
      
