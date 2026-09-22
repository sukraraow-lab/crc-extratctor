# Don't Remove Credit Tg - @VJ_Bots
# Subscribe YouTube Channel For Amazing Bot @Tech_VJ
# Ask Doubt on telegram @KingVJ01

import datetime

# Don't Remove Credit Tg - @VJ_Bots
# Subscribe YouTube Channel For Amazing Bot @Tech_VJ
# Ask Doubt on telegram @KingVJ01

def get_datetime_str():
    now = datetime.datetime.now()
    return now.strftime("%Y%m%d%H%M%S")

# Don't Remove Credit Tg - @VJ_Bots
# Subscribe YouTube Channel For Amazing Bot @Tech_VJ
# Ask Doubt on telegram @KingVJ01

def create_html_file(file_name, batch_name, contents):
    tbody = ''
    for line in contents:
        text, url = [item.strip('\n').strip() for item in line.split(':', 1)]
        tbody += f'<tr><td><a href="{url}">{text}</a></td></tr>'

    with open('template.html') as fp:
        file_content = fp.read()

    with open(file_name, 'w') as fp:
        fp.write(file_content.replace('tbody_content', tbody).replace('batch_name', batch_name))


# Don't Remove Credit Tg - @VJ_Bots
# Subscribe YouTube Channel For Amazing Bot @Tech_VJ
# Ask Doubt on telegram @KingVJ01
