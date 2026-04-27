import sqlite3
conn = sqlite3.connect('db.sqlite3')
c = conn.cursor()
c.execute("SELECT id, image FROM questions_question WHERE section_id IN (542,543,544) AND image != '' AND image IS NOT NULL")
print('Q images:', c.fetchall())
c2 = conn.cursor()
c2.execute("SELECT o.id, o.image FROM questions_option o JOIN questions_question q ON o.question_id=q.id WHERE q.section_id IN (542,543,544) AND o.image != '' AND o.image IS NOT NULL LIMIT 5")
print('Opt images:', c2.fetchall())
conn.close()
