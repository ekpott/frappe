# Copyright (c) 2013, Web Notes Technologies Pvt. Ltd. and Contributors
# MIT License. See license.txt

from __future__ import unicode_literals
from webnotes import conf
import webnotes
import json, os, time
from webnotes import _
import webnotes.utils
from webnotes.model.controller import DocListController
import mimetypes
from webnotes.website.doctype.website_sitemap.website_sitemap import add_to_sitemap, update_sitemap, remove_sitemap

class PageNotFoundError(Exception): pass

def render(page_name):
	"""render html page"""
	if not page_name:
		page_name = "index"
	
	if "/" in page_name:
		page_name = page_name.split("/")[0]

	try:
		html = render_page(page_name)
	except Exception:
		html = render_page("error")
	
	webnotes._response.data = html
	
def render_page(page_name):
	"""get page html"""
	set_content_type(page_name)
	
	if page_name.endswith('.html'):
		page_name = page_name[:-5]
	html = ''
			
	if not conf.disable_website_cache:
		html = webnotes.cache().get_value("page:" + page_name)
		from_cache = True

	if not html:
		html = build_page(page_name)
		from_cache = False
	
	if page_name=="error":
		html = html.replace("%(error)s", webnotes.get_traceback())
	elif "text/html" in webnotes._response.headers["Content-Type"]:
		comments = "\npage:"+page_name+\
			"\nload status: " + (from_cache and "cache" or "fresh")
		html += """\n<!-- %s -->""" % webnotes.utils.cstr(comments)

	return html
	
def set_content_type(page_name):
	webnotes._response.headers["Content-Type"] = "text/html; charset: utf-8"
	
	if "." in page_name and not page_name.endswith(".html"):
		content_type, encoding = mimetypes.guess_type(page_name)
		webnotes._response.headers["Content-Type"] = content_type

def build_page(page_name):
	if not webnotes.conn:
		webnotes.connect()

	if page_name=="index":
		page_name = get_home_page()
	try:
		sitemap_options = webnotes.doc("Website Sitemap", page_name).fields
		page_options = webnotes.doc("Website Sitemap Config", 
			sitemap_options.get("website_sitemap_config")).fields.update({
				"page_name":sitemap_options.page_name,
				"docname":sitemap_options.docname
			})
	except webnotes.DoesNotExistError:
		hooks = webnotes.get_hooks()
		if hooks.website_catch_all:
			return build_page(hooks.website_catch_all[0])
		else:
			return build_page("404")
		
	page_options["page_name"] = page_name
	
	no_cache = page_options.get("no_cache")

	# if generator, then load bean, pass arguments
	if page_options.get("page_or_generator")=="Generator":
		bean = webnotes.bean(page_options.get("ref_doctype"), page_options["docname"])
		bean.run_method("get_context")

		context = webnotes._dict(bean.doc.fields)
		context["obj"] = bean.get_controller()
	else:
		# page
		context = webnotes._dict({ 'name': page_name })
		if page_options.get("controller"):
			module = webnotes.get_module(page_options.get("controller"))
			if module and hasattr(module, "get_context"):
				context.update(module.get_context())
	
	context.update(get_website_settings())

	jenv = webnotes.get_jenv()
	context["base_template"] = jenv.get_template("templates/base.html")
	
	template_name = page_options['template_path']	
	context["_"] = webnotes._
	html = jenv.get_template(template_name).render(context)
	
	if not no_cache:
		webnotes.cache().set_value("page:" + page_name, html)
	return html
		
def get_home_page():
	return webnotes.cache().get_value("home_page", \
		lambda: webnotes.conn.get_value("Website Settings", None, "home_page") or "login")
	
def get_website_settings():
	from webnotes.utils import get_request_site_address, encode, cint
	from urllib import quote
	
	hooks = webnotes.get_hooks()
	
	all_top_items = webnotes.conn.sql("""\
		select * from `tabTop Bar Item`
		where parent='Website Settings' and parentfield='top_bar_items'
		order by idx asc""", as_dict=1)
	
	top_items = [d for d in all_top_items if not d['parent_label']]
	
	# attach child items to top bar
	for d in all_top_items:
		if d['parent_label']:
			for t in top_items:
				if t['label']==d['parent_label']:
					if not 'child_items' in t:
						t['child_items'] = []
					t['child_items'].append(d)
					break
					
	context = webnotes._dict({
		'top_bar_items': top_items,
		'footer_items': webnotes.conn.sql("""\
			select * from `tabTop Bar Item`
			where parent='Website Settings' and parentfield='footer_items'
			order by idx asc""", as_dict=1),
		"webnotes": webnotes,
		"utils": webnotes.utils,
		"post_login": [
			{"label": "Reset Password", "url": "update-password", "icon": "icon-key"},
			{"label": "Logout", "url": "/?cmd=web_logout", "icon": "icon-signout"}
		]
	})
		
	settings = webnotes.doc("Website Settings", "Website Settings")
	for k in ["banner_html", "brand_html", "copyright", "twitter_share_via",
		"favicon", "facebook_share", "google_plus_one", "twitter_share", "linked_in_share",
		"disable_signup"]:
		if k in settings.fields:
			context[k] = settings.fields.get(k)
			
	if settings.address:
		context["footer_address"] = settings.address

	for k in ["facebook_share", "google_plus_one", "twitter_share", "linked_in_share",
		"disable_signup"]:
		context[k] = cint(context.get(k) or 0)
	
	context.url = quote(str(get_request_site_address(full_address=True)), str(""))
	context.encoded_title = quote(encode(context.title or ""), str(""))
	
	for update_website_context in hooks.update_website_context or []:
		webnotes.get_attr(update_website_context)(context)
		
	context.web_include_js = hooks.web_include_js or []
	context.web_include_css = hooks.web_include_css or []
	
	return context

def clear_cache(page_name=None):
	if page_name:
		delete_page_cache(page_name)
	else:
		cache = webnotes.cache()
		for p in webnotes.conn.sql_list("""select name from `tabWebsite Sitemap`"""):
			if p is not None:
				cache.delete_value("page:" + p)
		cache.delete_value("home_page")
		cache.delete_value("page:index")
		cache.delete_value("website_sitemap")
		cache.delete_value("website_sitemap_config")
		
def delete_page_cache(page_name):
	if page_name:
		cache = webnotes.cache()
		cache.delete_value("page:" + page_name)
		cache.delete_value("website_sitemap")
			
def is_signup_enabled():
	if getattr(webnotes.local, "is_signup_enabled", None) is None:
		webnotes.local.is_signup_enabled = True
		if webnotes.utils.cint(webnotes.conn.get_value("Website Settings", 
			"Website Settings", "disable_signup")):
				webnotes.local.is_signup_enabled = False
		
	return webnotes.local.is_signup_enabled
	
def call_website_generator(bean, method):
	getattr(WebsiteGenerator(bean.doc, bean.doclist), method)()
	
class WebsiteGenerator(DocListController):
	def setup_generator(self):
		if webnotes.flags.in_install_app:
			return
		self._website_config = webnotes.conn.get_values("Website Sitemap Config", 
			{"ref_doctype": self.doc.doctype}, "*")[0]
			
	def on_update(self):
		self.update_sitemap()
		
	def after_rename(self, olddn, newdn, merge):
		webnotes.conn.sql("""update `tabWebsite Sitemap`
			set docname=%s where ref_doctype=%s and docname=%s""", (newdn, self.doc.doctype, olddn))
		
		if merge:
			self.setup_generator()
			remove_sitemap(ref_doctype=self.doc.doctype, docname=olddn)
		
	def on_trash(self):
		self.setup_generator()
		remove_sitemap(ref_doctype=self.doc.doctype, docname=self.doc.name)
		
	def update_sitemap(self):
		if webnotes.flags.in_install_app:
			return
		
		self.setup_generator()
		
		if self._website_config.condition_field and \
			not self.doc.fields.get(self._website_config.condition_field):
			# condition field failed, remove and return!
			remove_sitemap(ref_doctype=self.doc.doctype, docname=self.doc.name)
			return
				
		self.add_or_update_sitemap()
		
	def add_or_update_sitemap(self):
		page_name = self.get_page_name()
		
		existing_page_name = webnotes.conn.get_value("Website Sitemap", {"ref_doctype": self.doc.doctype,
			"docname": self.doc.name})
			
		opts = webnotes._dict({
			"page_or_generator": "Generator",
			"ref_doctype":self.doc.doctype, 
			"docname": self.doc.name,
			"page_name": page_name,
			"link_name": self._website_config.name,
			"lastmod": webnotes.utils.get_datetime(self.doc.modified).strftime("%Y-%m-%d"),
			"parent_website_sitemap": self.doc.parent_website_sitemap
		})
		
		if self.meta.get_field("public_read"):
			opts.public_read = self.doc.public_read
			opts.public_write = self.doc.public_write
		else:
			opts.public_read = 1
			
		if existing_page_name:
			if existing_page_name != page_name:
				webnotes.rename_doc("Website Sitemap", existing_page_name, page_name, ignore_permissions=True)
			update_sitemap(page_name, opts)
		else:
			add_to_sitemap(opts)
		
	def get_page_name(self):
		if not self.doc.fields.get(self._website_config.page_name_field):
			new_page_name = cleanup_page_name(self.get_page_title() \
				if hasattr(self, "get_page_title") else (self.doc.title or self.doc.name))
	
			webnotes.conn.set(self.doc, self._website_config.page_name_field, new_page_name)
			
		return self.doc.fields.get(self._website_config.page_name_field)
		
def cleanup_page_name(title):
	"""make page name from title"""
	import re
	name = title.lower()
	name = re.sub('[~!@#$%^&*+()<>,."\'\?]', '', name)
	name = re.sub('[:/]', '-', name)

	name = '-'.join(name.split())

	# replace repeating hyphens
	name = re.sub(r"(-)\1+", r"\1", name)
	
	return name

def get_hex_shade(color, percent):
	def p(c):
		v = int(c, 16) + int(int('ff', 16) * (float(percent)/100))
		if v < 0: 
			v=0
		if v > 255: 
			v=255
		h = hex(v)[2:]
		if len(h) < 2:
			h = "0" + h
		return h
		
	r, g, b = color[0:2], color[2:4], color[4:6]
	
	avg = (float(int(r, 16) + int(g, 16) + int(b, 16)) / 3)
	# switch dark and light shades
	if avg > 128:
		percent = -percent

	# stronger diff for darker shades
	if percent < 25 and avg < 64:
		percent = percent * 2
	
	return p(r) + p(g) + p(b)
