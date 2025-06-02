from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, authenticate, logout
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.views.decorators.http import require_POST, require_http_methods
from django.db.models import Sum, Q, Count, Avg
from django.utils import timezone
from django.http import JsonResponse, HttpResponse
from django.core.validators import MinValueValidator
from django.utils.text import slugify
import xlsxwriter
from io import BytesIO
from django.template.loader import get_template
from xhtml2pdf import pisa
import json
from datetime import timedelta, datetime
from django.urls import reverse

from .forms import LoginForm, RegisterForm, StaffForm
from .models import Service, Booking, User, Transaction, Staff, Review, BlogPost



def login_view(request):
    if request.user.is_authenticated:
        messages.info(request, "You are already logged in!")
        return redirect('dashboard')
        
    if request.method == 'POST':
        form = LoginForm(request, data=request.POST)
        if form.is_valid():
            username = form.cleaned_data.get('username')
            password = form.cleaned_data.get('password')
            remember_me = form.cleaned_data.get('remember_me', False)
            
            # Convert username to lowercase for consistency
            username = username.lower().strip()
            
            try:
                # First check if user exists
                try:
                    user_exists = User.objects.filter(username__iexact=username).exists()
                    if not user_exists:
                        messages.error(request, "No account found with this username. Please check your spelling or register for a new account.")
                        return render(request, 'registration/login.html', {'form': form})
                except Exception as e:
                    messages.error(request, f"Error checking username: {str(e)}")
                    return render(request, 'registration/login.html', {'form': form})
                
                # Attempt authentication
                user = authenticate(request, username=username, password=password)
                if user is not None:
                    if user.is_active:
                        login(request, user)
                        if not remember_me:
                            request.session.set_expiry(0)
                        messages.success(request, f"Welcome back, {user.username}! You have successfully logged in.")
                        
                        # Add session message
                        request.session['login_success'] = True
                        request.session['user_name'] = user.username
                        
                        # Clear any existing error messages
                        storage = messages.get_messages(request)
                        storage.used = True
                        
                        return redirect('dashboard')
                    else:
                        messages.error(request, "Your account is not active. Please contact the administrator.")
                else:
                    messages.error(request, "Invalid password. Please try again.")
            except Exception as e:
                messages.error(request, f"An error occurred during login: {str(e)}")
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f"{field.title()}: {error}")
    else:
        form = LoginForm()
        # Clear any existing messages when showing the login form
        storage = messages.get_messages(request)
        storage.used = True

    return render(request, 'registration/login.html', {'form': form})

def register_view(request):
    if request.user.is_authenticated:
        messages.info(request, "You are already registered and logged in!")
        return redirect('dashboard')
        
    if request.method == 'POST':
        form = RegisterForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            
            # Add success messages
            messages.success(request, f"Welcome {user.username}! Your account has been successfully created.")
            
            # Add session message
            request.session['registration_success'] = True
            request.session['user_name'] = user.username
            
            return redirect('dashboard')
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        form = RegisterForm()
    return render(request, 'registration/register.html', {'form': form})

def logout_view(request):
    username = request.user.username
    logout(request)
    messages.success(request, f"Goodbye {username}! You have been successfully logged out.")
    return redirect('login')


@login_required(login_url='login')
def dashboard(request):
    try:
        # Check for login/registration success messages
        if request.session.get('login_success'):
            messages.success(request, f"Welcome to your dashboard, {request.session.get('user_name')}!")
            del request.session['login_success']
            if 'user_name' in request.session:
                del request.session['user_name']
        
        if request.session.get('registration_success'):
            messages.success(request, f"Thank you for registering! Welcome to Storm's Beach and Country Club.")
            del request.session['registration_success']
            if 'user_name' in request.session:
                del request.session['user_name']

        # Get dashboard statistics
        context = {
            'total_bookings': Booking.objects.count(),
            'pending_bookings': Booking.objects.filter(status='pending').count(),
            'total_services': Service.objects.count(),
            'recent_bookings': Booking.objects.order_by('-created_at')[:5],
            'user': request.user
        }
        
        return render(request, 'dashboard.html', context)
    except Exception as e:
        messages.error(request, f"Error loading dashboard data: {str(e)}")
        # Instead of redirecting, render the dashboard with basic context
        return render(request, 'dashboard.html', {
            'user': request.user,
            'error': str(e)
        })

@login_required
def booking_view(request):
    # Get all bookings ordered by creation date with related data
    bookings = Booking.objects.select_related('guest', 'service').all().order_by('-created_at')
    
    # Get today's date
    today = timezone.now().date()
    
    # Calculate today's bookings
    today_bookings = bookings.filter(check_in__date=today).count()
    
    # Calculate today's revenue
    today_revenue = bookings.filter(check_in__date=today).aggregate(
        total=Sum('service__base_price'))['total'] or 0
    
    # Calculate occupancy rate (example: assuming 100 total capacity)
    total_capacity = 100
    current_bookings = bookings.filter(
        check_in__date=today,
        status='confirmed'
    ).count()
    occupancy_rate = (current_bookings / total_capacity) * 100 if total_capacity > 0 else 0
    
    # Calculate changes (comparing to yesterday)
    yesterday = today - timedelta(days=1)
    yesterday_bookings = bookings.filter(check_in__date=yesterday).count()
    yesterday_revenue = bookings.filter(check_in__date=yesterday).aggregate(
        total=Sum('service__base_price'))['total'] or 0
    yesterday_occupancy = bookings.filter(
        check_in__date=yesterday,
        status='confirmed'
    ).count()
    
    # Calculate percentage changes
    booking_change = ((today_bookings - yesterday_bookings) / yesterday_bookings * 100 
                     if yesterday_bookings > 0 else 0)
    revenue_change = ((today_revenue - yesterday_revenue) / yesterday_revenue * 100 
                     if yesterday_revenue > 0 else 0)
    occupancy_change = ((current_bookings - yesterday_occupancy) / yesterday_occupancy * 100 
                       if yesterday_occupancy > 0 else 0)
    
    # Get current guests (guests with active bookings)
    current_guests = bookings.filter(
        check_in__date__lte=today,
        check_out__date__gte=today,
        status='confirmed'
    ).count()
    
    # Get all services for the edit modal
    services = Service.objects.all()
    
    context = {
        'bookings': bookings,
        'today_bookings': today_bookings,
        'today_revenue': today_revenue,
        'occupancy_rate': round(occupancy_rate, 1),
        'current_guests': current_guests,
        'today_booking_change': f"{round(booking_change, 1)}%",
        'revenue_change': f"{round(revenue_change, 1)}%",
        'occupancy_change': round(occupancy_change, 1),
        'guest_change': current_guests - yesterday_occupancy,
        'services': services,
    }
    
    return render(request, 'uiadmin/booking.html', context)

@login_required
def blogs_view(request):
    # Get blog posts with stats
    blog_posts = BlogPost.objects.select_related('author').all()
    
    # Calculate stats
    total_posts = blog_posts.count()
    published_posts = blog_posts.filter(status='published').count()
    draft_posts = blog_posts.filter(status='draft').count()
    
    context = {
        'blog_posts': blog_posts,
        'total_posts': total_posts,
        'published_posts': published_posts,
        'draft_posts': draft_posts,
    }
    
    return render(request, 'blogs.html', context)

@login_required
def services_view(request):
    if request.method == 'POST':
        try:
            # Get form data
            service_name = request.POST.get('service_name')
            description = request.POST.get('description')
            base_price = request.POST.get('base_price')
            pricing_type = request.POST.get('pricing_type')
            status = request.POST.get('status')
            max_capacity = request.POST.get('max_capacity')
            additional_info = request.POST.get('additional_info')
            image = request.FILES.get('image')

            # Validate required fields
            if not all([service_name, description, base_price, pricing_type, status]):
                return JsonResponse({
                    'success': False,
                    'error': 'Please fill in all required fields.'
                }, status=400)

            # Validate pricing type
            if pricing_type not in dict(Service.PRICING_TYPE_CHOICES):
                return JsonResponse({
                    'success': False,
                    'error': 'Invalid pricing type selected.'
                }, status=400)

            # Validate status
            if status not in dict(Service.STATUS_CHOICES):
                return JsonResponse({
                    'success': False,
                    'error': 'Invalid status selected.'
                }, status=400)

            try:
                base_price = float(base_price)
                if base_price < 0:
                    raise ValueError
            except ValueError:
                return JsonResponse({
                    'success': False,
                    'error': 'Base price must be a valid positive number.'
                }, status=400)

            # Create new service
            service = Service.objects.create(
                name=service_name,
                description=description,
                base_price=base_price,
                pricing_type=pricing_type,
                status=status,
                max_capacity=max_capacity if max_capacity else None,
                additional_info=additional_info,
                image=image
            )

            # Calculate updated stats
            services = Service.objects.all()
            available_services = services.filter(status='available').count()
            average_price = services.aggregate(avg_price=Avg('base_price'))['avg_price']
            if average_price:
                average_price = round(average_price, 2)

            # Prepare service data for response
            service_data = {
                'id': service.id,
                'name': service.name,
                'description': service.description,
                'base_price': float(service.base_price),
                'status': service.status,
                'image_url': service.image.url if service.image else None
            }

            return JsonResponse({
                'success': True,
                'message': f'Service "{service.name}" has been added successfully!',
                'service': service_data,
                'stats': {
                    'total_services': services.count(),
                    'available_services': available_services,
                    'average_price': average_price
                }
            })

        except Exception as e:
            print(f"Error adding service: {str(e)}")  # Add debug print
            return JsonResponse({
                'success': False,
                'error': f'Error adding service: {str(e)}'
            }, status=500)

    # GET request - show services list
    services = Service.objects.all()
    available_services = services.filter(status='available').count()
    average_price = services.aggregate(avg_price=Avg('base_price'))['avg_price']
    if average_price:
        average_price = round(average_price, 2)

    context = {
        'services': services,
        'average_price': average_price,
        'available_services': available_services,
        'pricing_types': Service.PRICING_TYPE_CHOICES,
        'status_choices': Service.STATUS_CHOICES,
    }
    return render(request, 'services.html', context)

@login_required
def staff_view(request):
    # Get all staff members from the Staff model
    staff_members = Staff.objects.all()
    
    # Calculate statistics
    total_staff = staff_members.count()
    active_staff = staff_members.filter(status='active').count()
    
    # Get unique departments
    departments = staff_members.values_list('department', flat=True).distinct().count()
    
    # Create form instance for the modal
    form = StaffForm()
    
    context = {
        'staff_members': staff_members,
        'total_staff': total_staff,
        'active_staff': active_staff,
        'total_departments': departments,
        'form': form,
    }
    
    return render(request, 'staff_dashboard.html', context)

@login_required
def staff_dashboard(request):
    # Get all staff members
    staff_members = Staff.objects.all()
    
    # Calculate statistics
    total_staff = staff_members.count()
    active_staff = staff_members.filter(status='active').count()
    
    # Get unique departments
    departments = staff_members.values_list('department', flat=True).distinct().count()
    
    context = {
        'staff_members': staff_members,
        'total_staff': total_staff,
        'active_staff': active_staff,
        'total_departments': departments,
    }
    
    return render(request, 'staff_dashboard.html', context)

# API endpoints for AJAX operations
@login_required
def update_booking(request, booking_id):
    if request.method == 'POST':
        booking = Booking.objects.get(id=booking_id)
        status = request.POST.get('status')
        if status in dict(Booking.STATUS_CHOICES):
            booking.status = status
            booking.save()
            messages.success(request, f"Booking {booking.booking_id} has been updated.")
        else:
            messages.error(request, "Invalid status provided.")
    return redirect('booking')

@login_required
def delete_booking(request, booking_id):
    if request.method == 'POST':
        booking = Booking.objects.get(id=booking_id)
        booking.delete()
        messages.success(request, f"Booking {booking.booking_id} has been deleted.")
    return redirect('booking')

@login_required
def add_booking_view(request):
    if request.method == 'POST':
        try:
            # Debug print
            print("Headers:", request.headers)
            print("POST data:", request.POST)
            print("Files:", request.FILES)
            
            # Get form data
            name = request.POST.get('name', '').strip()
            contact = request.POST.get('contact', '').strip()
            email = request.POST.get('email', '').strip()
            service_id = request.POST.get('service', '').strip()
            check_in = request.POST.get('check_in', '').strip()
            check_out = request.POST.get('check_out', '').strip()
            number_of_guests = request.POST.get('number_of_guests', '').strip()
            payment_method = request.POST.get('payment_method', '').strip()
            special_requests = request.POST.get('special_requests', '').strip()

            # Debug print
            print("Parsed form data:")
            print(f"name: '{name}'")
            print(f"contact: '{contact}'")
            print(f"service_id: '{service_id}'")
            print(f"check_in: '{check_in}'")
            print(f"check_out: '{check_out}'")
            print(f"number_of_guests: '{number_of_guests}'")

            # Validate required fields
            missing_fields = []
            if not name: missing_fields.append('name')
            if not contact: missing_fields.append('contact')
            if not service_id: missing_fields.append('service')
            if not check_in: missing_fields.append('check-in date')
            if not check_out: missing_fields.append('check-out date')
            if not number_of_guests: missing_fields.append('number of guests')
            
            if missing_fields:
                print(f"Missing fields: {missing_fields}")  # Debug print
                return JsonResponse({
                    'success': False,
                    'message': f'Please fill in all required fields: {", ".join(missing_fields)}'
                })

            # Get service object
            try:
                service = Service.objects.get(id=service_id)
            except Service.DoesNotExist:
                print(f"Service with ID {service_id} not found")  # Debug print
                return JsonResponse({
                    'success': False,
                    'message': 'Selected service does not exist.'
                })
            except ValueError:
                print(f"Invalid service ID: {service_id}")  # Debug print
                return JsonResponse({
                    'success': False,
                    'message': 'Invalid service selected.'
                })

            # Convert dates to datetime
            try:
                check_in_date = timezone.make_aware(datetime.strptime(check_in, '%Y-%m-%d'))
                check_out_date = timezone.make_aware(datetime.strptime(check_out, '%Y-%m-%d'))
            except ValueError as e:
                print(f"Date conversion error: {str(e)}")  # Debug print
                return JsonResponse({
                    'success': False,
                    'message': f'Invalid date format: {str(e)}'
                })

            # Validate number of guests
            try:
                number_of_guests = int(number_of_guests)
                if number_of_guests < 1:
                    raise ValueError("Number of guests must be at least 1")
            except ValueError as e:
                print(f"Invalid number of guests: {str(e)}")  # Debug print
                return JsonResponse({
                    'success': False,
                    'message': 'Invalid number of guests. Please enter a valid number.'
                })

            # Generate unique booking ID
            booking_id = f"BK{timezone.now().strftime('%Y%m%d%H%M%S')}"

            # Create new booking
            try:
                booking = Booking.objects.create(
                    booking_id=booking_id,
                    guest=request.user,
                    service=service,
                    check_in=check_in_date,
                    check_out=check_out_date,
                    number_of_guests=number_of_guests,
                    special_requests=special_requests,
                    status='pending',
                    payment_method=payment_method if payment_method else None
                )
                print(f"Booking created successfully: {booking}")  # Debug print

                # Store success message in session
                request.session['booking_success'] = True
                request.session['booking_id'] = booking.booking_id

                # Prepare booking data for response
                booking_data = {
                    'id': booking.id,
                    'booking_id': booking.booking_id,
                    'guest_name': booking.guest.get_full_name() or booking.guest.username,
                    'service_name': booking.service.name,
                    'check_in': booking.check_in.strftime('%Y-%m-%d'),
                    'check_out': booking.check_out.strftime('%Y-%m-%d'),
                    'status': booking.status
                }

                return JsonResponse({
                    'success': True,
                    'message': f'Booking #{booking.booking_id} has been created successfully!',
                    'redirect_url': reverse('booking'),
                    'booking': booking_data
                })

            except Exception as e:
                print(f"Error creating booking: {str(e)}")  # Debug print
                return JsonResponse({
                    'success': False,
                    'message': f'Error creating booking: {str(e)}'
                })

        except Exception as e:
            print(f"Unexpected error: {str(e)}")  # Debug print
            return JsonResponse({
                'success': False,
                'message': f'An unexpected error occurred: {str(e)}'
            })

    # For GET request, show the form
    services = Service.objects.all()
    context = {
        'services': services,
        'today': timezone.now().date()
    }
    return render(request, 'uiadmin/addbooking.html', context)

@login_required
def update_transaction_status(request, transaction_id):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            status = data.get('status')
            
            if status not in dict(Transaction.STATUS_CHOICES):
                return JsonResponse({'success': False, 'error': 'Invalid status'}, status=400)
            
            transaction = Transaction.objects.get(id=transaction_id)
            transaction.status = status
            
            # If refunding, create a new refund transaction
            if status == 'refunded' and transaction.status != 'refunded':
                Transaction.objects.create(
                    booking=transaction.booking,
                    amount=transaction.amount,
                    payment_method=transaction.payment_method,
                    status='success',
                    transaction_type='refund',
                    notes=f'Refund for transaction {transaction.transaction_id}'
                )
            
            transaction.save()
            messages.success(request, f"Transaction {transaction.transaction_id} has been updated to {status}.")
            return JsonResponse({'success': True})
            
        except Transaction.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'Transaction not found'}, status=404)
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)}, status=500)
    
    return JsonResponse({'success': False, 'error': 'Invalid request method'}, status=405)

@login_required
def transaction_list(request):
    # Get search query if exists
    search_query = request.GET.get('search', '')

    # Base queryset
    transactions = Transaction.objects.select_related('booking', 'booking__guest', 'booking__service').all()

    if search_query:
        transactions = transactions.filter(
            Q(transaction_id__icontains=search_query) |
            Q(booking__guest__username__icontains=search_query) |
            Q(booking__guest__first_name__icontains=search_query) |
            Q(booking__guest__last_name__icontains=search_query) |
            Q(booking__service__name__icontains=search_query) |
            Q(reference_code__icontains=search_query)
        )

    transactions = transactions.order_by('-transaction_date')[:50]

    # Calculate stats
    today = timezone.now().date()
    last_month = today - timedelta(days=30)

    # Total revenue (successful payments only)
    total_revenue = Transaction.objects.filter(
        status='success',
        transaction_type='payment',
        transaction_date__date=today
    ).aggregate(total=Sum('amount'))['total'] or 0

    last_month_revenue = Transaction.objects.filter(
        status='success',
        transaction_type='payment',
        transaction_date__date__gte=last_month,
        transaction_date__date__lt=today
    ).aggregate(total=Sum('amount'))['total'] or 0

    revenue_change = calculate_percentage_change(last_month_revenue, total_revenue)

    # Refunds issued
    total_refunds = Transaction.objects.filter(
        transaction_type='refund',
        transaction_date__date=today
    ).aggregate(total=Sum('amount'))['total'] or 0

    last_month_refunds = Transaction.objects.filter(
        transaction_type='refund',
        transaction_date__date__gte=last_month,
        transaction_date__date__lt=today
    ).aggregate(total=Sum('amount'))['total'] or 0

    refund_change = calculate_percentage_change(last_month_refunds, total_refunds)

    # Failed transactions
    failed_transactions = Transaction.objects.filter(
        status='failed',
        transaction_date__date=today
    ).count()

    last_month_failed = Transaction.objects.filter(
        status='failed',
        transaction_date__date__gte=last_month,
        transaction_date__date__lt=today
    ).count()

    failed_change = calculate_percentage_change(last_month_failed, failed_transactions)

    # Most popular payment method
    payment_method_stats = Transaction.objects.filter(
        transaction_date__date=today
    ).values('payment_method').annotate(
        count=Count('id'),
        total=Sum('amount')
    ).order_by('-count')

    if payment_method_stats:
        popular_method = dict(Transaction.PAYMENT_METHODS).get(payment_method_stats[0]['payment_method'])
        method_percentage = round(
            (payment_method_stats[0]['count'] / sum(m['count'] for m in payment_method_stats)) * 100)
    else:
        popular_method = "GCash"
        method_percentage = 0

    context = {
        'transactions': transactions,
        'total_revenue': total_revenue,
        'revenue_change': revenue_change,
        'total_refunds': total_refunds,
        'refund_change': refund_change,
        'failed_transactions': failed_transactions,
        'failed_change': failed_change,
        'popular_method': popular_method,
        'method_percentage': f"{method_percentage}%",
        'users': User.objects.all(),
        'services': Service.objects.all(),
        'payment_methods': Transaction.PAYMENT_METHODS,
        'status_choices': Transaction.STATUS_CHOICES,
        'search_query': search_query,
    }

    return render(request, 'transactions/transaction_list.html', context)

@login_required
def edit_transaction(request, pk):
    transaction = get_object_or_404(Transaction, pk=pk)
    return JsonResponse({
        'id': transaction.id,
        'transaction_id': transaction.transaction_id,
        'booking_id': transaction.booking.id,
        'user_id': transaction.booking.guest.id,
        'service_id': transaction.booking.service.id,
        'amount': str(transaction.amount),
        'payment_method': transaction.payment_method,
        'status': transaction.status,
        'transaction_type': transaction.transaction_type,
        'transaction_date': transaction.transaction_date.isoformat(),
        'reference_code': transaction.reference_code,
    })

@require_POST
@login_required
def update_transaction(request, pk):
    try:
        transaction = get_object_or_404(Transaction, pk=pk)
        
        # Validate amount
        try:
            amount = float(request.POST.get('amount', transaction.amount))
            if amount <= 0:
                raise ValueError("Amount must be greater than 0")
            transaction.amount = amount
        except ValueError as e:
            return JsonResponse({'success': False, 'error': str(e)})
        
        # Validate and update other fields
        payment_method = request.POST.get('payment_method')
        status = request.POST.get('status')
        transaction_type = request.POST.get('transaction_type')
        
        if payment_method not in dict(Transaction.PAYMENT_METHODS):
            return JsonResponse({'success': False, 'error': 'Invalid payment method'})
        if status not in dict(Transaction.STATUS_CHOICES):
            return JsonResponse({'success': False, 'error': 'Invalid status'})
        if transaction_type not in ['payment', 'refund']:
            return JsonResponse({'success': False, 'error': 'Invalid transaction type'})
            
        transaction.payment_method = payment_method
        transaction.status = status
        transaction.transaction_type = transaction_type
        transaction.reference_code = request.POST.get('reference_code')

        # Update booking if changed
        booking_id = request.POST.get('booking_id')
        if booking_id and int(booking_id) != transaction.booking.id:
            booking = get_object_or_404(Booking, pk=booking_id)
            transaction.booking = booking

        transaction.save()
        messages.success(request, f"Transaction {transaction.transaction_id} has been updated successfully.")
        return JsonResponse({'success': True})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

@require_POST
@login_required
def delete_transaction(request, pk):
    try:
        transaction = get_object_or_404(Transaction, pk=pk)
        transaction_id = transaction.transaction_id
        transaction.delete()
        messages.success(request, f"Transaction {transaction_id} has been deleted successfully.")
        return JsonResponse({'success': True})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

@login_required
def transaction_receipt(request, pk):
    transaction = get_object_or_404(Transaction, pk=pk)
    template = get_template('transactions/receipt.html')
    context = {
        'transaction': transaction,
        'booking': transaction.booking,
        'guest': transaction.booking.guest,
        'service': transaction.booking.service,
    }
    
    html = template.render(context)
    result = BytesIO()
    pdf = pisa.pisaDocument(BytesIO(html.encode("UTF-8")), result)
    
    if not pdf.err:
        response = HttpResponse(result.getvalue(), content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="receipt_{transaction.transaction_id}.pdf"'
        return response
    return HttpResponse('Error generating PDF', status=500)

@login_required
def export_transactions(request):
    output = BytesIO()
    workbook = xlsxwriter.Workbook(output)
    worksheet = workbook.add_worksheet()

    # Add headers
    headers = [
        'Transaction ID', 'Date', 'Guest', 'Service', 'Amount',
        'Payment Method', 'Status', 'Type', 'Reference Code'
    ]
    for col, header in enumerate(headers):
        worksheet.write(0, col, header)

    # Get transactions
    transactions = Transaction.objects.select_related(
        'booking', 'booking__guest', 'booking__service'
    ).order_by('-transaction_date')

    # Write data
    for row, trans in enumerate(transactions, start=1):
        worksheet.write(row, 0, trans.transaction_id)
        worksheet.write(row, 1, trans.transaction_date.strftime('%Y-%m-%d %H:%M:%S'))
        worksheet.write(row, 2, f"{trans.booking.guest.get_full_name()}")
        worksheet.write(row, 3, trans.booking.service.name)
        worksheet.write(row, 4, float(trans.amount))
        worksheet.write(row, 5, dict(Transaction.PAYMENT_METHODS)[trans.payment_method])
        worksheet.write(row, 6, dict(Transaction.STATUS_CHOICES)[trans.status])
        worksheet.write(row, 7, trans.transaction_type)
        worksheet.write(row, 8, trans.reference_code or '')

    workbook.close()
    output.seek(0)

    response = HttpResponse(
        output.read(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = 'attachment; filename=transactions.xlsx'
    return response

def calculate_percentage_change(old_value, new_value):
    if old_value == 0:
        return 100 if new_value > 0 else 0
    return round(((new_value - old_value) / old_value) * 100, 1)

@login_required
@require_POST
def delete_service(request, service_id):
    try:
        service = get_object_or_404(Service, id=service_id)
        service.delete()
        return JsonResponse({'success': True})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

@login_required
def edit_service(request, service_id):
    service = get_object_or_404(Service, id=service_id)
    
    if request.method == 'POST':
        try:
            # Get form data
            service_name = request.POST.get('service_name')
            description = request.POST.get('description')
            base_price = request.POST.get('base_price')
            pricing_type = request.POST.get('pricing_type')
            status = request.POST.get('status')
            max_capacity = request.POST.get('max_capacity')
            additional_info = request.POST.get('additional_info')
            image = request.FILES.get('image')

            # Validate required fields
            if not all([service_name, description, base_price, pricing_type, status]):
                return JsonResponse({
                    'success': False,
                    'errors': {
                        'service_name': ['Service name is required.'] if not service_name else [],
                        'description': ['Description is required.'] if not description else [],
                        'base_price': ['Base price is required.'] if not base_price else [],
                        'pricing_type': ['Pricing type is required.'] if not pricing_type else [],
                        'status': ['Status is required.'] if not status else []
                    }
                }, status=400)

            # Validate pricing type
            if pricing_type not in dict(Service.PRICING_TYPE_CHOICES):
                return JsonResponse({
                    'success': False,
                    'errors': {'pricing_type': ['Invalid pricing type selected.']}
                }, status=400)

            # Validate status
            if status not in dict(Service.STATUS_CHOICES):
                return JsonResponse({
                    'success': False,
                    'errors': {'status': ['Invalid status selected.']}
                }, status=400)

            try:
                base_price = float(base_price)
                if base_price < 0:
                    raise ValueError
            except ValueError:
                return JsonResponse({
                    'success': False,
                    'errors': {'base_price': ['Base price must be a valid positive number.']}
                }, status=400)

            # Update service
            service.name = service_name
            service.description = description
            service.base_price = base_price
            service.pricing_type = pricing_type
            service.status = status
            service.max_capacity = max_capacity if max_capacity else None
            service.additional_info = additional_info
            if image:
                service.image = image
            service.save()

            # Prepare service data for response
            service_data = {
                'id': service.id,
                'name': service.name,
                'description': service.description,
                'base_price': float(service.base_price),
                'status': service.status,
                'image_url': service.image.url if service.image else None
            }

            return JsonResponse({
                'success': True,
                'message': f'Service "{service.name}" has been updated successfully!',
                'service': service_data
            })

        except Exception as e:
            return JsonResponse({
                'success': False,
                'errors': {'__all__': [str(e)]}
            }, status=500)

    # Get data for form dropdowns
    context = {
        'service': service,
        'pricing_types': Service.PRICING_TYPE_CHOICES,
        'status_choices': Service.STATUS_CHOICES,
    }
    return render(request, 'uiadmin/editservice.html', context)

@login_required
def add_staff(request):
    if request.method == 'POST':
        form = StaffForm(request.POST, request.FILES)
        if form.is_valid():
            staff = form.save()
            return JsonResponse({
                'success': True,
                'message': f'Staff member "{staff.name}" has been added successfully!',
                'staff': {
                    'id': staff.id,
                    'name': staff.name,
                    'position': staff.position,
                    'department': staff.department,
                    'email': staff.email,
                    'phone': staff.phone,
                    'status': staff.status,
                    'image_url': staff.image.url if staff.image else None,
                }
            })
        else:
            return JsonResponse({
                'success': False,
                'errors': form.errors
            }, status=400)
    
    form = StaffForm()
    return render(request, 'staff/add_staff.html', {'form': form})

@login_required
def get_staff_details(request, staff_id):
    try:
        staff = get_object_or_404(Staff, id=staff_id)
        return JsonResponse({
            'id': staff.id,
            'name': staff.name,
            'employee_id': staff.employee_id,
            'position': staff.position,
            'department': staff.department,
            'email': staff.email,
            'phone': staff.phone,
            'status': staff.status,
            'image_url': staff.image.url if staff.image else None,
        })
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)

@login_required
def edit_staff(request, staff_id):
    try:
        staff = get_object_or_404(Staff, id=staff_id)
        
        if request.method == 'POST':
            form = StaffForm(request.POST, request.FILES, instance=staff)
            if form.is_valid():
                staff = form.save()
                return JsonResponse({
                    'success': True,
                    'message': f'Staff member "{staff.name}" has been updated successfully!',
                    'staff': {
                        'id': staff.id,
                        'name': staff.name,
                        'position': staff.position,
                        'department': staff.department,
                        'email': staff.email,
                        'phone': staff.phone,
                        'status': staff.status,
                        'image_url': staff.image.url if staff.image else None,
                    }
                })
            else:
                return JsonResponse({
                    'success': False,
                    'errors': form.errors
                }, status=400)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)

@login_required
def delete_staff(request, staff_id):
    if request.method == 'POST':
        try:
            staff = get_object_or_404(Staff, id=staff_id)
            staff_name = staff.name
            staff.delete()
            return JsonResponse({
                'success': True,
                'message': f'Staff member "{staff_name}" has been deleted successfully!'
            })
        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': str(e)
            }, status=500)
    return JsonResponse({'error': 'Invalid request method'}, status=405)

@login_required
def get_service_details(request, service_id):
    try:
        service = get_object_or_404(Service, id=service_id)
        return JsonResponse({
            'id': service.id,
            'name': service.name,
            'description': service.description,
            'base_price': float(service.base_price),
            'pricing_type': service.pricing_type,
            'status': service.status,
            'max_capacity': service.max_capacity,
            'additional_info': service.additional_info,
            'image_url': service.image.url if service.image else None,
        })
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)

def is_admin(user):
    return user.is_staff or user.is_superuser

@login_required
@user_passes_test(is_admin)
def reviews_dashboard(request):
    reviews = Review.objects.select_related('user').all()
    stats = {
        'total_reviews': reviews.count(),
        'average_rating': reviews.aggregate(Avg('rating'))['rating__avg'] or 0,
        'pending_reviews': reviews.filter(status='pending').count(),
    }
    
    context = {
        'reviews': reviews,
        'total_reviews': stats['total_reviews'],
        'average_rating': stats['average_rating'],
        'pending_reviews': stats['pending_reviews'],
    }
    return render(request, 'reviews.html', context)

@login_required
@user_passes_test(is_admin)
@require_http_methods(["POST"])
def update_review_status(request, review_id):
    try:
        data = json.loads(request.body)
        status = data.get('status')
        
        if status not in ['pending', 'approved', 'rejected']:
            return JsonResponse({'success': False, 'error': 'Invalid status'}, status=400)
        
        review = Review.objects.get(id=review_id)
        review.status = status
        review.save()
        
        return JsonResponse({
            'success': True,
            'message': f'Review status updated to {status}'
        })
    except Review.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Review not found'}, status=404)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)

@login_required
@user_passes_test(is_admin)
def get_review_details(request, review_id):
    try:
        review = Review.objects.get(id=review_id)
        return JsonResponse({
            'success': True,
            'rating': review.rating,
            'content': review.content,
            'status': review.status,
        })
    except Review.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Review not found'}, status=404)

@login_required
@user_passes_test(is_admin)
@require_http_methods(["POST"])
def edit_review(request, review_id):
    try:
        review = Review.objects.get(id=review_id)
        review.rating = request.POST.get('rating')
        review.content = request.POST.get('content')
        review.status = request.POST.get('status')
        review.save()
        
        return JsonResponse({
            'success': True,
            'message': 'Review updated successfully'
        })
    except Review.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Review not found'}, status=404)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)

@login_required
@user_passes_test(is_admin)
@require_http_methods(["POST"])
def delete_review(request, review_id):
    try:
        review = Review.objects.get(id=review_id)
        review.delete()
        return JsonResponse({
            'success': True,
            'message': 'Review deleted successfully'
        })
    except Review.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Review not found'}, status=404)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)

@login_required
def get_blog_details(request, post_id):
    try:
        post = BlogPost.objects.get(id=post_id)
        return JsonResponse({
            'success': True,
            'title': post.title,
            'content': post.content,
            'status': post.status,
            'featured_image_url': post.featured_image.url if post.featured_image else None,
        })
    except BlogPost.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Blog post not found'}, status=404)

@login_required
@require_http_methods(["POST"])
def add_blog_post(request):
    try:
        # Get form data
        title = request.POST.get('title')
        content = request.POST.get('content')
        status = request.POST.get('status')
        featured_image = request.FILES.get('featured_image')

        # Validate required fields
        if not all([title, content, status]):
            return JsonResponse({
                'success': False,
                'error': 'Please fill in all required fields'
            }, status=400)

        # Create new blog post
        post = BlogPost.objects.create(
            title=title,
            content=content,
            status=status,
            author=request.user,
            featured_image=featured_image,
            published_date=timezone.now() if status == 'published' else None
        )

        return JsonResponse({
            'success': True,
            'message': 'Blog post created successfully',
            'post': {
                'id': post.id,
                'title': post.title,
                'status': post.status,
            }
        })
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)

@login_required
@require_http_methods(["POST"])
def edit_blog_post(request, post_id):
    try:
        post = BlogPost.objects.get(id=post_id)
        
        # Get form data
        title = request.POST.get('title')
        content = request.POST.get('content')
        status = request.POST.get('status')
        featured_image = request.FILES.get('featured_image')

        # Validate required fields
        if not all([title, content, status]):
            return JsonResponse({
                'success': False,
                'error': 'Please fill in all required fields'
            }, status=400)

        # Update blog post
        post.title = title
        post.content = content
        post.status = status
        if featured_image:
            post.featured_image = featured_image
        
        # Update published date if status changes to published
        if status == 'published' and post.published_date is None:
            post.published_date = timezone.now()
        
        post.save()

        return JsonResponse({
            'success': True,
            'message': 'Blog post updated successfully'
        })
    except BlogPost.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Blog post not found'}, status=404)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)

@login_required
@require_http_methods(["POST"])
def delete_blog_post(request, post_id):
    try:
        post = BlogPost.objects.get(id=post_id)
        post.delete()
        return JsonResponse({
            'success': True,
            'message': 'Blog post deleted successfully'
        })
    except BlogPost.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Blog post not found'}, status=404)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)

@login_required
@require_POST
def clear_booking_session(request):
    """Clear booking-related session variables."""
    if 'booking_success' in request.session:
        del request.session['booking_success']
    if 'booking_id' in request.session:
        del request.session['booking_id']
    return JsonResponse({'success': True})