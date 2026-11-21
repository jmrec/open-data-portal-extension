from plugin import postprocess_site

if __name__ == "__main__":
    postprocess_site(
        site_dir="site",
        docs_dir="docs",
        site_url="https://ph-boundaries-docs.jmrecondo.com",
        add_desc=True,
        add_image=True,
        add_authors=True,
        add_json_ld=True,
        add_share_buttons=False,
        add_css=True,
        add_copy_llm=False,
        verbose=True,
    )