# Copyright 2010 http://www.collabq.com
# Copyright 2009 Google Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""django template tags for showing errors in UI
"""

__author__ = 'teemu@google.com (Teemu Kurppa)'

from django import template

register = template.Library()

@register.filter(name="error_to_html")
def error_to_html(error):
    return error.to_html()