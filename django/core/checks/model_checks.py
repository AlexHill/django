# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import inspect
import types
from itertools import chain

from django.apps import apps
from django.core.checks import Error, Tags, register
from django.db import models


@register(Tags.models)
def check_all_models(app_configs=None, **kwargs):
    errors = []
    if app_configs is None:
        models = apps.get_models()
    else:
        models = chain.from_iterable(app_config.get_models() for app_config in app_configs)
    for model in models:
        if not inspect.ismethod(model.check):
            errors.append(
                Error(
                    "The '%s.check()' class method is "
                    "currently overridden by %r." % (
                        model.__name__, model.check),
                    hint=None,
                    obj=model,
                    id='models.E020'
                )
            )
        else:
            errors.extend(model.check(**kwargs))
    return errors


def _check_lazy_references(app_registry, ignore=None):
    """
    Ensure all lazy (i.e. string) model references have been resolved.

    Lazy references are used in various places throughout Django, primarily in
    related fields and model signals. We identify those common cases, and
    provide more helpful error messages for them.

    The ignore parameter is used by StateApps to exclude swappable models from
    this check.
    """
    pending_models = set(app_registry._pending_operations) - (ignore or set())

    # Short-circuit if there are no errors.
    if not pending_models:
        return []

    model_signals = {signal: name for name, signal in vars(models.signals).items()
                     if isinstance(signal, models.signals.ModelSignal)}

    def extract_operation(obj):
        """
        Take a callable found in Apps._pending_operations and identify the
        original function passed to Apps.lazy_model_operation(). If that
        function was a partial, return the inner, non-partial function and any
        arguments and keyword arguments that were supplied with it.

        obj could be one of three things:
        * a plain function waiting to be called
        * a partial, which has a 'func' attribute
        * a callback defined locally in Apps.add_lazy_operation() and
          annotated there with a 'func' attribute
        """
        operation, args, keywords = obj, [], {}
        while hasattr(operation, 'func'):
            args.extend(getattr(operation, 'args', []))
            keywords.update(getattr(operation, 'keywords', {}))
            operation = operation.func
        return operation, args, keywords

    # Here we define several functions which return CheckMessage instances for
    # the most common usages of lazy operations throughout Django. These
    # functions take the model that was being waited on as an (app_label,
    # modelname) pair, the original lazy function, and its positional and
    # keyword args as determined by extract_operation().

    def field_error(model_key, func, args, keywords):
        error_msg = (
            "The field %(field)s was declared with a lazy reference "
            "to '%(model)s', which is not installed."
        )
        params = {
            'model': '.'.join(model_key),
            'field': keywords['field'],
        }
        return Error(error_msg % params, obj=keywords['field'], hint=None, id='fields.E020')

    def signal_connect_error(model_key, func, args, keywords):
        error_msg = (
            "%(receiver)s was connected to the '%(signal)s' signal "
            "with a lazy reference to the '%(model)s' sender, "
            "which has not been installed."
        )
        receiver = args[0]
        # The receiver is either a function or an instance of class
        # defining a `__call__` method.
        if isinstance(receiver, types.FunctionType):
            description = "The '%s' function" % receiver.__name__
        else:
            description = "An instance of the '%s' class" % receiver.__class__.__name__
        signal_name = model_signals.get(func.__self__, 'unknown')
        params = {
            'model': '.'.join(model_key),
            'receiver': description,
            'signal': signal_name
        }
        return Error(error_msg % params, obj=receiver.__module__, hint=None, id='signals.E001')

    def default_error(model_key, func, args, keywords):
        error_msg = "Unhandled lazy reference to '%(model)s': %(op)s."
        params = {
            'model': '.'.join(model_key),
            'op': func
        }
        return Error(error_msg % params, obj=func, hint=None)

    # Maps common uses of lazy operations to corresponding error functions
    # defined above. If a key maps to None, no error will be produced.
    # default_error() will be used for usages that don't appear in this dict.
    known_lazy = {
        ('django.db.models.fields.related', 'resolve_related_class'): field_error,
        ('django.db.models.fields.related', 'set_managed'): None,
        ('django.dispatch.dispatcher', 'connect'): signal_connect_error,
    }

    def build_error(model_key, func, args, keywords):
        key = (func.__module__, func.__name__)
        error_fn = known_lazy.get(key, default_error)
        return error_fn(model_key, func, args, keywords) if error_fn else None

    errors = sorted(filter(None, (
        build_error(model_key, *extract_operation(func))
        for model_key in pending_models
        for func in app_registry._pending_operations[model_key]
    )), key=lambda error: error.msg)

    print()
    for error in errors:
        print(error)
    print()

    return errors


@register(Tags.models)
def check_lazy_references(app_configs=None, **kwargs):
    return _check_lazy_references(apps)
