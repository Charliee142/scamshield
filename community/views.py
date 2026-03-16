# community/views.py
from django.shortcuts import render, redirect
from django.contrib import messages
from core.models import ScamReport
from scanner.views import get_nigerian_states

def report_scam(request):
    # context defined at top level so it's available for both GET and POST
    context = {
        'nigerian_states': get_nigerian_states(),
        'total_reports': ScamReport.objects.count(),
    }

    if request.method == "POST":
        phone = request.POST.get("phone_number", "").strip()
        account = request.POST.get("account_number", "").strip()
        bank = request.POST.get("bank_name", "").strip()
        scam_type = request.POST.get("scam_type")
        description = request.POST.get("description", "").strip()
        state = request.POST.get("state", "other")
        screenshot = request.FILES.get("screenshot")

        if description and scam_type:
            # Check if phone already reported
            if phone:
                existing = ScamReport.objects.filter(phone_number=phone).first()
                if existing:
                    existing.report_count += 1
                    existing.save()
                    messages.warning(request, f"This number has been reported {existing.report_count} times!")
                    return redirect('phone_lookup')

            ScamReport.objects.create(
                phone_number=phone,
                account_number=account,
                bank_name=bank,
                scam_type=scam_type,
                description=description,
                state=state,
                screenshot=screenshot
            )
            messages.success(request, "✅ Thank you! Your report helps protect other Nigerians.")
            return redirect('report_scam')

    return render(request, 'community/report.html', context)


def phone_lookup(request):
    result = None
    query = request.GET.get("q", "").strip()
    if query:
        reports = ScamReport.objects.filter(phone_number__icontains=query)
        if reports.exists():
            total = sum(r.report_count for r in reports)
            result = {
                'query': query,
                'reports': reports,
                'total_reports': total,
                'is_scammer': True
            }
        else:
            result = {'query': query, 'is_scammer': False}

    return render(request, 'community/phone_lookup.html', {'result': result})