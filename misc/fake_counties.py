# Script to generate ca_all_counties_fire_records_contacts_template.csv

import csv

filename = 'ca_all_counties_fire_records_contacts_template.csv'
fieldnames = ['County', 'Request Email']
counties = [
    'Los Angeles', 'San Francisco', 'San Diego', 'Sacramento', 'Fresno',
    'Alameda', 'Santa Clara', 'Orange', 'Riverside', 'San Bernardino'
]

with open(filename, 'w', newline='') as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    for county in counties:
        writer.writerow({'County': county, 'Request Email': 'sillaskon@gmail.com'})

print(f'{filename} generated successfully with all emails set to sillaskon@gmail.com.')
