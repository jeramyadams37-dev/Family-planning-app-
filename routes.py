from flask import session, render_template, request, redirect, url_for, jsonify, flash
from app import app, db
from replit_auth import require_login, make_replit_blueprint
from flask_login import current_user
from models import User, FamilyProfile, Event, Chore, Photo, Memory, RemembranceMember, Message, Family, UserWallet, DataConsent, TokenTransaction, Post, PostLike, PostComment
from ai_helper import get_family_ai_response, generate_family_tree_insights, suggest_family_activities
from email_helper import send_family_invite_email
from data_marketplace import get_or_create_wallet, get_or_create_consent, award_tokens, simulate_data_earnings
from upload_helper import save_uploaded_file, delete_uploaded_file
from datetime import datetime, timedelta
from sqlalchemy import or_
import os

app.register_blueprint(make_replit_blueprint(), url_prefix="/auth")

# Make session permanent
@app.before_request
def make_session_permanent():
    session.permanent = True


@app.route('/')
def index():
    """Landing page for logged out users, home for logged in users"""
    if not current_user.is_authenticated:
        return render_template('landing.html')
    
    # Check if user needs to setup their family
    if not current_user.family_id:
        return redirect(url_for('family_setup'))
    
    # Get user's profile or create one if it doesn't exist
    profile = FamilyProfile.query.filter_by(user_id=current_user.id).first()
    if not profile:
        profile = FamilyProfile(user_id=current_user.id)
        db.session.add(profile)
        db.session.commit()
    
    # Get upcoming events (next 30 days) for this family only
    upcoming_events = Event.query.filter(
        Event.family_id == current_user.family_id,
        Event.event_date >= datetime.now(),
        Event.event_date <= datetime.now() + timedelta(days=30)
    ).order_by(Event.event_date).limit(5).all()
    
    # Get pending chores for this family
    pending_chores = Chore.query.filter_by(
        family_id=current_user.family_id,
        assigned_to=current_user.id,
        status='pending'
    ).order_by(Chore.due_date).limit(5).all()
    
    # Get unread messages count
    unread_count = Message.query.filter_by(
        receiver_id=current_user.id,
        is_read=False
    ).count()
    
    # Get recent memories for this family only
    recent_memories = Memory.query.join(RemembranceMember).filter(
        RemembranceMember.family_id == current_user.family_id
    ).order_by(Memory.created_at.desc()).limit(3).all()
    
    return render_template('home.html',
                         profile=profile,
                         upcoming_events=upcoming_events,
                         pending_chores=pending_chores,
                         unread_count=unread_count,
                         recent_memories=recent_memories)


@app.route('/family/setup', methods=['GET', 'POST'])
@require_login
def family_setup():
    """Setup or join a family"""
    if current_user.family_id:
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'create':
            surname = request.form.get('surname')
            description = request.form.get('description')
            
            if not surname:
                flash('Family surname is required!', 'error')
                return redirect(url_for('family_setup'))
            
            # Generate unique invite code
            invite_code = Family.generate_invite_code()
            while Family.query.filter_by(invite_code=invite_code).first():
                invite_code = Family.generate_invite_code()
            
            # Create new family
            family = Family(
                surname=surname,
                invite_code=invite_code,
                created_by=current_user.id,
                description=description
            )
            db.session.add(family)
            db.session.flush()
            
            # Assign user to family and make them admin
            current_user.family_id = family.id
            current_user.is_family_admin = True
            db.session.commit()
            
            flash(f'Welcome to the {surname} family! Share your invite code: {invite_code}', 'success')
            return redirect(url_for('index'))
        
        elif action == 'join':
            invite_code = request.form.get('invite_code', '').strip().upper()
            
            if not invite_code:
                flash('Invite code is required!', 'error')
                return redirect(url_for('family_setup'))
            
            family = Family.query.filter_by(invite_code=invite_code).first()
            
            if not family:
                flash('Invalid invite code!', 'error')
                return redirect(url_for('family_setup'))
            
            # Join the family
            current_user.family_id = family.id
            db.session.commit()
            
            flash(f'Welcome to the {family.surname} family!', 'success')
            return redirect(url_for('index'))
    
    return render_template('family_setup.html')


@app.route('/family/manage')
@require_login
def manage_family():
    """Manage family settings and view invite code"""
    if not current_user.family_id:
        return redirect(url_for('family_setup'))
    
    family = Family.query.get(current_user.family_id)
    members = User.query.filter_by(family_id=family.id).all()
    
    return render_template('manage_family.html', family=family, members=members)


@app.route('/family/regenerate-invite', methods=['POST'])
@require_login
def regenerate_invite():
    """Regenerate family invite code (admin only)"""
    if not current_user.is_family_admin:
        flash('Only family administrators can regenerate invite codes.', 'error')
        return redirect(url_for('manage_family'))
    
    family = Family.query.get(current_user.family_id)
    
    # Generate new unique invite code
    new_code = Family.generate_invite_code()
    while Family.query.filter_by(invite_code=new_code).first():
        new_code = Family.generate_invite_code()
    
    family.invite_code = new_code
    db.session.commit()
    
    flash(f'New invite code generated: {new_code}', 'success')
    return redirect(url_for('manage_family'))


@app.route('/family/send-invite', methods=['POST'])
@require_login
def send_invite():
    """Send family invite via email"""
    if not current_user.family_id:
        flash('You must be part of a family to send invites.', 'error')
        return redirect(url_for('family_setup'))
    
    family = Family.query.get(current_user.family_id)
    recipient_email = request.form.get('recipient_email', '').strip()
    
    if not recipient_email:
        flash('Please provide a recipient email address.', 'error')
        return redirect(url_for('manage_family'))
    
    try:
        # Get the app URL
        app_url = request.url_root.rstrip('/')
        
        # Get inviter name
        inviter_name = current_user.first_name or 'A family member'
        
        # Send the invite email
        send_family_invite_email(
            recipient_email=recipient_email,
            family_name=family.surname,
            invite_code=family.invite_code,
            inviter_name=inviter_name,
            app_url=app_url
        )
        
        flash(f'Invite sent to {recipient_email}!', 'success')
    except Exception as e:
        flash(f'Failed to send invite: {str(e)}', 'error')
    
    return redirect(url_for('manage_family'))


@app.route('/profile/<user_id>')
@require_login
def view_profile(user_id):
    """View any family member's profile (within same family only)"""
    if not current_user.family_id:
        return redirect(url_for('family_setup'))
    
    user = User.query.get_or_404(user_id)
    
    # Security: Only allow viewing profiles within the same family
    if user.family_id != current_user.family_id:
        flash('You can only view profiles within your own family.', 'error')
        return redirect(url_for('family_members'))
    
    profile = FamilyProfile.query.filter_by(user_id=user_id).first()
    
    if not profile:
        profile = FamilyProfile(user_id=user_id)
        db.session.add(profile)
        db.session.commit()
    
    can_edit = (current_user.id == user_id)
    
    return render_template('profile.html', 
                         user=user, 
                         profile=profile, 
                         can_edit=can_edit)


@app.route('/profile/edit', methods=['GET', 'POST'])
@require_login
def edit_profile():
    """Edit own profile (users can only edit their own)"""
    profile = FamilyProfile.query.filter_by(user_id=current_user.id).first()
    
    if not profile:
        profile = FamilyProfile(user_id=current_user.id)
        db.session.add(profile)
    
    if request.method == 'POST':
        # Update profile fields
        profile.age = request.form.get('age', type=int)
        profile.role = request.form.get('role')
        profile.interests = request.form.get('interests')
        profile.favorite_things = request.form.get('favorite_things')
        profile.bio = request.form.get('bio')
        profile.legacy_hope_remembered_for = request.form.get('legacy_hope_remembered_for')
        profile.legacy_impact_on_family = request.form.get('legacy_impact_on_family')
        
        db.session.commit()
        flash('Profile updated successfully!', 'success')
        return redirect(url_for('view_profile', user_id=current_user.id))
    
    return render_template('edit_profile.html', profile=profile)


@app.route('/family')
@require_login
def family_members():
    """View all family members"""
    if not current_user.family_id:
        return redirect(url_for('family_setup'))
    
    members = User.query.filter_by(family_id=current_user.family_id).all()
    family = Family.query.get(current_user.family_id)
    return render_template('family_members.html', members=members, family=family)


@app.route('/calendar')
@require_login
def calendar():
    """Shared family calendar with events and chores"""
    if not current_user.family_id:
        return redirect(url_for('family_setup'))
    
    events = Event.query.filter_by(family_id=current_user.family_id).order_by(Event.event_date).all()
    chores = Chore.query.filter_by(family_id=current_user.family_id).order_by(Chore.due_date).all()
    
    return render_template('calendar.html', events=events, chores=chores)


@app.route('/event/create', methods=['GET', 'POST'])
@require_login
def create_event():
    """Create a new family event"""
    if not current_user.family_id:
        return redirect(url_for('family_setup'))
    
    if request.method == 'POST':
        event_date_str = request.form.get('event_date')
        if not event_date_str:
            flash('Event date is required!', 'error')
            return redirect(url_for('create_event'))
        
        event = Event(
            creator_id=current_user.id,
            family_id=current_user.family_id,
            title=request.form.get('title'),
            description=request.form.get('description'),
            event_type=request.form.get('event_type'),
            event_date=datetime.fromisoformat(event_date_str),
            location=request.form.get('location'),
            is_recurring=request.form.get('is_recurring') == 'on'
        )
        db.session.add(event)
        db.session.commit()
        flash('Event created successfully!', 'success')
        return redirect(url_for('calendar'))
    
    return render_template('create_event.html')


@app.route('/chore/create', methods=['GET', 'POST'])
@require_login
def create_chore():
    """Create a new chore"""
    if not current_user.family_id:
        return redirect(url_for('family_setup'))
    
    if request.method == 'POST':
        chore = Chore(
            family_id=current_user.family_id,
            title=request.form.get('title'),
            description=request.form.get('description'),
            assigned_to=request.form.get('assigned_to'),
            due_date=datetime.fromisoformat(request.form.get('due_date')) if request.form.get('due_date') else None,
            priority=request.form.get('priority', 'medium')
        )
        db.session.add(chore)
        db.session.commit()
        flash('Chore created successfully!', 'success')
        return redirect(url_for('calendar'))
    
    family_members = User.query.filter_by(family_id=current_user.family_id).all()
    return render_template('create_chore.html', family_members=family_members)


@app.route('/chore/<int:chore_id>/update', methods=['POST'])
@require_login
def update_chore_status(chore_id):
    """Update chore status"""
    chore = Chore.query.get_or_404(chore_id)
    
    # Security: Only allow updating chores within the same family
    if chore.family_id != current_user.family_id:
        return jsonify({'success': False, 'error': 'Not authorized'}), 403
    
    if chore.assigned_to == current_user.id:
        chore.status = request.form.get('status', 'pending')
        db.session.commit()
        return jsonify({'success': True})
    
    return jsonify({'success': False, 'error': 'Not authorized'}), 403


@app.route('/remembrance')
@require_login
def remembrance():
    """Memorial page for beloved family members who have passed"""
    if not current_user.family_id:
        return redirect(url_for('family_setup'))
    
    remembered_members = RemembranceMember.query.filter_by(family_id=current_user.family_id).all()
    return render_template('remembrance.html', remembered_members=remembered_members)


@app.route('/remembrance/<int:member_id>')
@require_login
def remembrance_detail(member_id):
    """Detailed memorial page with memories"""
    member = RemembranceMember.query.get_or_404(member_id)
    
    # Security: Only allow viewing remembrance members within the same family
    if member.family_id != current_user.family_id:
        flash('You can only view remembrance pages within your own family.', 'error')
        return redirect(url_for('remembrance'))
    
    tributes = Memory.query.filter_by(remembrance_member_id=member_id).order_by(Memory.created_at.desc()).all()
    return render_template('remembrance_detail.html', member=member, tributes=tributes)


@app.route('/remembrance/add', methods=['POST'])
@require_login
def add_remembrance_member():
    """Add a new member to the remembrance wall"""
    if not current_user.family_id:
        flash('❌ Please join a family first', 'error')
        return redirect(url_for('family_setup'))
    
    name = request.form.get('name', '').strip()
    if not name:
        flash('❌ Name is required', 'error')
        return redirect(url_for('remembrance'))
    
    # Parse dates
    birth_date = None
    passing_date = None
    
    if request.form.get('birth_date'):
        birth_date = datetime.strptime(request.form.get('birth_date'), '%Y-%m-%d').date()
    if request.form.get('passing_date'):
        passing_date = datetime.strptime(request.form.get('passing_date'), '%Y-%m-%d').date()
    
    # Handle photo upload
    photo_url = None
    if 'photo' in request.files:
        file = request.files['photo']
        if file and file.filename:
            photo_url, _, _ = save_uploaded_file(file)
    
    member = RemembranceMember(
        family_id=current_user.family_id,
        name=name,
        birth_date=birth_date,
        passing_date=passing_date,
        role=request.form.get('role', '').strip(),
        photo_url=photo_url,
        life_story=request.form.get('life_story', '').strip(),
        favorite_quote=request.form.get('favorite_quote', '').strip(),
        legacy=request.form.get('legacy', '').strip(),
        
        # Personal Connection & Memories
        relationship_to_submitter=request.form.get('relationship_to_submitter', '').strip(),
        favorite_memories=request.form.get('favorite_memories', '').strip(),
        legacy_in_effect=request.form.get('legacy_in_effect', '').strip(),
        
        # Genealogy & Heritage
        place_of_birth=request.form.get('place_of_birth', '').strip(),
        place_of_passing=request.form.get('place_of_passing', '').strip(),
        occupation=request.form.get('occupation', '').strip(),
        achievements=request.form.get('achievements', '').strip(),
        hobbies_interests=request.form.get('hobbies_interests', '').strip(),
        personality_traits=request.form.get('personality_traits', '').strip(),
        special_traditions=request.form.get('special_traditions', '').strip(),
        maiden_name=request.form.get('maiden_name', '').strip(),
        parents_names=request.form.get('parents_names', '').strip(),
        siblings_names=request.form.get('siblings_names', '').strip(),
        children_names=request.form.get('children_names', '').strip()
    )
    
    db.session.add(member)
    db.session.commit()
    
    flash(f'✅ {name} has been added to the remembrance wall', 'success')
    return redirect(url_for('remembrance'))


@app.route('/remembrance/<int:member_id>/memory', methods=['POST'])
@require_login
def add_memory(member_id):
    """Add a memory/comment about a beloved family member"""
    member = RemembranceMember.query.get_or_404(member_id)
    
    # Security: Only allow adding memories for remembrance members within the same family
    if member.family_id != current_user.family_id:
        flash('You can only add memories for remembrance members within your own family.', 'error')
        return redirect(url_for('remembrance'))
    
    memory = Memory(
        remembrance_member_id=member_id,
        author_id=current_user.id,
        title=request.form.get('title'),
        content=request.form.get('content'),
        memory_date=datetime.fromisoformat(request.form.get('memory_date')) if request.form.get('memory_date') else None
    )
    db.session.add(memory)
    db.session.commit()
    flash('Memory shared successfully!', 'success')
    return redirect(url_for('remembrance_detail', member_id=member_id))


@app.route('/remembrance/<int:member_id>/tribute', methods=['POST'])
@require_login
def add_remembrance_tribute(member_id):
    """Add a tribute to a beloved family member"""
    member = RemembranceMember.query.get_or_404(member_id)
    
    # Security: Only allow adding tributes for remembrance members within the same family
    if member.family_id != current_user.family_id:
        flash('You can only add tributes for remembrance members within your own family.', 'error')
        return redirect(url_for('remembrance'))
    
    tribute_content = request.form.get('tribute_content', '').strip()
    if not tribute_content:
        flash('Please write a tribute message.', 'error')
        return redirect(url_for('remembrance_detail', member_id=member_id))
    
    memory = Memory(
        remembrance_member_id=member_id,
        author_id=current_user.id,
        title=None,
        content=tribute_content,
        memory_date=None
    )
    db.session.add(memory)
    db.session.commit()
    flash('🕊️ Tribute shared successfully!', 'success')
    return redirect(url_for('remembrance_detail', member_id=member_id))


@app.route('/photos')
@require_login
def photos():
    """Photo gallery"""
    if not current_user.family_id:
        return redirect(url_for('family_setup'))
    
    all_photos = Photo.query.filter_by(family_id=current_user.family_id).order_by(Photo.created_at.desc()).all()
    
    # Group photos by album
    albums = {}
    for photo in all_photos:
        album_name = photo.album_name or 'General'
        if album_name not in albums:
            albums[album_name] = []
        albums[album_name].append(photo)
    

return render_template('photos.html', albums=albums)


@app.route('/messages')
@require_login
def messages():
    """View messages"""
    if not current_user.family_id:
        return redirect(url_for('family_setup'))
    
    received = Messa
