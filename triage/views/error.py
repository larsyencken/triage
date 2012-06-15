from pyramid.view import view_config
from pyramid.renderers import render_to_response
from pyramid.httpexceptions import HTTPFound, HTTPNotFound

from triage.models import Error, Comment, Tag, User, ErrorInstance
from time import time
from os import path

import logging

def get_errors(request, fetch_recent=False):
    selected_project = get_selected_project(request)

    log = logging.getLogger(__name__)

    search = request.GET.get('search', '')
    show = request.GET.get('show', 'open')  # open, resolved, mine
    tags = request.GET.getall('tags')
    order_by = request.GET.get('order_by', 'date')
    direction = request.GET.get('direction', 'desc')
    start = int(request.GET.get('start', 0))
    time_latest = int(request.GET.get('timelatest', time()))

    if show not in ['open', 'resolved', 'mine']:
        show = 'open'

    if show == 'open':
        errors = Error.objects.active(selected_project)
    elif show == 'resolved':
        errors = Error.objects.resolved(selected_project)
    elif show == 'mine':
        errors = Error.objects.active(selected_project).filter(claimedby=request.user)

    if search:
        errors.search(search)

    if tags:
        errors.filter(tags__in=tags)

    if fetch_recent:
        return errors.filter(timelatest__gt=time_latest).count()

    errors.filter(timelatest__lte=time_latest)

    order_map = {
        'date': 'timelatest',
        'occurances': 'count',
        'activity': 'comments'
    }

    if order_by in order_map:
        order_by = order_map[order_by]
    else:
        order_by = 'timelatest'

    if direction == 'desc':
        order_by = '-' + order_by

    errors.order_by(order_by)

    pagedErrors = errors.skip(start).limit(20)

    log.debug(errors.count())
    log.debug(pagedErrors.count())

    return list(pagedErrors)


@view_config(route_name='error_list', permission='authenticated', xhr=True, renderer='errors/list.html')
def error_list(request):
    return {
        'selected_project': get_selected_project(request),
        'errors': get_errors(request),
        'basename': path.basename
    }


@view_config(route_name='error_list', permission='authenticated', xhr=False, renderer='error-list.html')
def error_page(request):
    available_projects = request.registry.settings['projects']
    selected_project = get_selected_project(request)

    search = request.GET.get('search', '')
    show = request.GET.get('show', 'open')  # open, resolved, mine
    order_by = request.GET.get('order_by', 'date')
    direction = request.GET.get('direction', 'desc')

    if show not in ['open', 'resolved', 'mine']:
        show = 'open'

    errors = get_errors(request)

    counts = {
        'open': Error.objects.active(selected_project).filter(seenby__ne=request.user).count(),
        'resolved': Error.objects.resolved(selected_project).filter(seenby__ne=request.user).count(),
        'mine': Error.objects.active(selected_project).filter(claimedby=request.user).count()
    }

    return {
        'search': search,
        'errors': errors,
        'selected_project': selected_project,
        'available_projects': available_projects,
        'show': show,
        'order_by': order_by,
        'direction': direction,
        'counts': counts,
        'basename': path.basename
    }


@view_config(route_name='error_list_changes', permission='authenticated', xhr=True, renderer='json')
def error_list_changes(request):
    return get_errors(request, True)


@view_config(route_name='error_view', permission='authenticated')
def view(request):
    available_projects = request.registry.settings['projects']
    selected_project = get_selected_project(request)

    error_id = request.matchdict['id']
    try:
        error = Error.objects().with_id(error_id)
    except:
        return HTTPNotFound()
    if request.user not in error.seenby:
        error.seenby.append(request.user)
        error.save()

    instances = ErrorInstance.objects(hash=error.hash)[:10]

    params = {
        'error': error,
        'selected_project': selected_project,
        'available_projects': available_projects,
        'instances': instances
    }

    try:
        template = 'error-view/' + str(error['language']).lower() + '.html'
        return render_to_response(template, params)
    except:
        template = 'error-view/generic.html'
        return render_to_response(template, params)



@view_config(route_name='error_toggle_claim', permission='authenticated', xhr=True, renderer='json')
def toggle_claim(request):
    error_id = request.matchdict['id']
    selected_project = get_selected_project(request)

    try:
        error = Error.objects(project=selected_project['id']).with_id(error_id)
        if error.claimedby and error.claimedby != request.user:
            return {'type': 'failure'}

        error.claimedby = None if error.claimedby else request.user
        error.save()

        return {'type': 'success'}
    except:
        return {'type': 'failure'}


@view_config(route_name='error_toggle_resolve', permission='authenticated', xhr=True, renderer='json')
def toggle_resolve(request):
    error_id = request.matchdict['id']
    selected_project = get_selected_project(request)

    try:
        error = Error.objects(project=selected_project['id']).with_id(error_id)
        if error.hiddenby and error.hiddenby != request.user:
            return {'type': 'failure'}

        error.hiddenby = None if error.hiddenby else request.user
        error.save()

        return {'type': 'success'}
    except:
        return {'type': 'failure'}


@view_config(route_name='error_tag_add', permission='authenticated', xhr=True, renderer='json')
def tag_add(request):
    tag = request.matchdict['tag']
    error_id = request.matchdict['id']
    selected_project = get_selected_project(request)

    try:
        error = Error.objects(project=selected_project['id']).with_id(error_id)
        if tag in error.tags:
            return {'type': 'failure'}

        error.tags.append(tag)
        error.save()
        Tag.create(tag).save()
        return {'type': 'success'}
    except:
        return {'type': 'failure'}


@view_config(route_name='error_tag_remove', permission='authenticated', xhr=True, renderer='json')
def tag_remove(request):
    tag = request.matchdict['tag']
    error_id = request.matchdict['id']
    selected_project = get_selected_project(request)

    try:
        error = Error.objects(project=selected_project['id']).with_id(error_id)
        if tag not in error.tags:
            return {'type': 'failure'}

        error.tags.remove(tag)
        error.save()
        Tag.removeOne(tag)
        return {'type': 'success'}
    except:
        return {'type': 'failure'}


@view_config(route_name='error_comment_add', permission='authenticated', xhr=True, renderer='json')
def comment_add(request):
    error_id = request.matchdict['id']
    selected_project = get_selected_project(request)

    try:
        error = Error.objects(project=selected_project['id']).with_id(error_id)
        error.comments.append(Comment(
            author=request.user,
            content=request.POST.get('comment').strip(),
            created=int(time())
        ))
        error.save()
        return {'type': 'success'}
    except:
        return {'type': 'failure'}


@view_config(route_name='error_toggle_hide')
def toggle_hide(request):
    error_id = request.matchdict['id']
    selected_project = get_selected_project(request)

    try:
        error = Error.objects(project=selected_project['id']).with_id(error_id)
        error.hiddenby = None if error.hiddenby else request.user
        error.save()

        url = request.route_url('error_view', project=selected_project['id'], id=error_id)
        return HTTPFound(location=url)
    except:
        return HTTPNotFound()


def get_selected_project(request):
    selected_project_key = request.matchdict['project']
    available_projects = request.registry.settings['projects']

    if selected_project_key in available_projects:
        return available_projects[selected_project_key]
    else:
        raise HTTPNotFound()
